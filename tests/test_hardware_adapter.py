"""Adapter contracts, without pretending the omitted native bodies were supplied."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from types import SimpleNamespace as NS
from unittest.mock import Mock

from alerters.hardware.plugin import Candidate, HardwarePlugin, SourceAdapter
from dealcore.types import Listing
from dealcore.verdict import qualifies
from scripts.import_hardware import rewrite


class Bands(IntEnum):
    PASS = 0
    FAIR = 1
    GOOD = 2
    STRONG = 3
    EXCEPTIONAL = 4
    GRAIL = 5


@dataclass
class NativeAssessment:
    unit_price: float = 600
    verdict: Bands = Bands.STRONG
    vram_before: float = 18
    vram_after: float = 16
    loggable: bool = True
    dollars_per_gb: float = 37.5
    dollars_per_gb_bandwidth: float = 40.1
    reason: str = "Capped for no upgrade; target subsequently promoted it"
    target_hit: bool = False
    unlock: str = "No new model fits"


class HardwareAdapterTests(unittest.TestCase):
    def plugin(self):
        plugin = HardwarePlugin.__new__(HardwarePlugin)
        plugin.bands = Bands
        plugin.cfg = NS(thresholds=NS(min_observations=8, min_observation_days=14), psu_headroom_w=150)
        plugin.log = Mock()
        return plugin

    def candidate(self, condition="refurbished"):
        row = Listing("v1|123|456", "ebay", "A card", "https://example.test",
                      datetime.now(timezone.utc), price=600, condition_hint=condition)
        matched = NS(part=NS(key="a6000"), unit_price=600, quantity=1, mining_risk="low",
                     is_system=False, is_bundle=False)
        return Candidate(row, matched, NS(target=700, name="upgrade"), condition)

    def test_target_cannot_undo_cap_or_bypass_a_lower_configured_floor(self):
        plugin = self.plugin()
        plugin.verdict = NS(assess=Mock(return_value=NativeAssessment()))
        assessment = plugin.judge(self.candidate(), NS())
        self.assertEqual(assessment.verdict, Bands.GOOD)
        self.assertFalse(assessment.alertable)
        self.assertFalse(qualifies(assessment, Bands.GOOD))
        plugin.verdict.assess.return_value = NativeAssessment(vram_after=42)
        self.assertTrue(qualifies(plugin.judge(self.candidate(), NS()), Bands.STRONG))

    def test_a_trusted_target_hit_reaches_push(self):
        # Observed 2026-09-22: "[gpu] rtx 5090 for $4299 at Walmart" was the
        # cheapest 5090 in 30 days, and a target could only lift it to STRONG,
        # below push.
        plugin = self.plugin()
        plugin.verdict = NS(assess=Mock(return_value=NativeAssessment(vram_after=42, target_hit=True)))
        self.assertTrue(qualifies(plugin.judge(self.candidate(), NS()), Bands.EXCEPTIONAL))

    def test_a_target_hit_held_back_as_bait_stays_off_the_phone(self):
        plugin = self.plugin()
        plugin.verdict = NS(assess=Mock(return_value=NativeAssessment(
            vram_after=42, target_hit=True, verdict=Bands.GOOD)))
        self.assertFalse(qualifies(plugin.judge(self.candidate(), NS()), Bands.EXCEPTIONAL))

    def test_a_target_hit_never_overrides_the_upgrade_cap(self):
        plugin = self.plugin()
        plugin.verdict = NS(assess=Mock(return_value=NativeAssessment(target_hit=True)))
        self.assertFalse(qualifies(plugin.judge(self.candidate(), NS()), Bands.EXCEPTIONAL))

    def test_a_buildapcsales_post_is_new_unless_it_says_otherwise(self):
        plugin = self.plugin()
        plugin.seen = plugin.matched = 0
        plugin.cfg.max_listing_age_hours = 72
        plugin.watched = {"rtx_5090": NS(target=5000, name="RTX 5090")}
        cases = (("reddit/buildapcsales", "unknown", "new"),
                 ("reddit/buildapcsales", "open_box", "open_box"),
                 ("reddit/hardwareswap", "unknown", "unknown"))
        for source, detected, expected in cases:
            plugin.matcher = Mock(return_value=NS(junk=False, part=NS(key="rtx_5090"),
                                                  unit_price=4299, condition=detected))
            row = Listing("1wnci76", source, "[gpu] rtx 5090 for $4299 at Walmart",
                          "https://example.test", datetime.now(timezone.utc), price=4299)
            self.assertEqual(plugin.prepare(row).condition, expected, source)

    def test_condition_and_confidence_requirements_pass_through_unchanged(self):
        plugin = self.plugin()
        sold, pooled = NS(trustworthy=False), NS(trustworthy=False)
        plugin.log.stats.side_effect = [sold, pooled]
        self.assertIs(plugin.read_history(self.candidate()), pooled)
        first, second = plugin.log.stats.call_args_list
        self.assertEqual(first.args, ("a6000", "refurbished"))
        self.assertEqual(first.kwargs, {"sold_only": True, "min_observations": 8, "min_span_days": 14})
        self.assertEqual(second.args, ("a6000", "refurbished"))
        plugin.log.stats.reset_mock()
        trusted = NS(trustworthy=True)
        plugin.log.stats.side_effect = [trusted]
        self.assertIs(plugin.read_history(self.candidate("new")), trusted)
        plugin.log.stats.assert_called_once_with("a6000", "new", sold_only=True,
                                                min_observations=8, min_span_days=14)

    def test_search_window_never_claims_complete_enumeration(self):
        adapter = SourceAdapter(NS(name="ebay", fetch=lambda: [self.candidate().listing]))
        batch = adapter.fetch()
        self.assertEqual(len(batch.listings), 1)
        self.assertFalse(batch.complete_sources)

    def test_importer_preserves_comments_and_refuses_unknown_source_shapes(self):
        text = '# Why this survives.\ndef old():\n    return 1\n\n# Domain reasoning.\ndef kept():\n    return 2\n'
        changed = rewrite(text, {"old": "from other import shared as old"})
        self.assertIn("# Why this survives.", changed)
        self.assertIn("# Domain reasoning.\ndef kept():\n    return 2", changed)
        compile(changed, "migrated.py", "exec")
        with self.assertRaises(ValueError):
            rewrite(text, {"missing": ""})
