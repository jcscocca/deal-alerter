"""Workflow regressions using deliberately non-shopping domain semantics."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from alerters.hardware.identity import group_id, normalise_key
from dealcore.notify import Channel
from dealcore.run import RunOptions, dedupe, run
from dealcore.state import AlertState
from dealcore.types import AccumulatedHistory, Assessment, Card, DelegatedHistory, FetchResult, Listing, Report, SourceError
from dealcore.verdict import Improvement, qualifies

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


class Bands(IntEnum):
    SKIP = -4
    NOTICE = 17


def listing(identity="a", *, source="test", price=10.0, **kwargs):
    return Listing(identity, source, "A listing", "https://example.test/item", NOW,
                   price=price, **kwargs)


def item(key="test:a", price=10.0, verdict=Bands.NOTICE):
    return Assessment(key, price, verdict, None, axes=(("only", "evidence"),))


class Domain:
    name, bands, axes = "test", Bands, ("only",)

    def __init__(self, rows, *, complete=False, accumulated=False):
        self.events, self.saved, self.closed = [], False, False
        batch = FetchResult(rows, frozenset({"test"}) if complete else frozenset())
        self.sources = (SimpleNamespace(name="test", fetch=lambda: batch),)
        self.history = (AccumulatedHistory(self.read, self.append) if accumulated
                        else DelegatedHistory(self.read))

    @staticmethod
    def key(row):
        return f"{row.source}:{group_id(row.listing_id)}"

    normalise_key = staticmethod(normalise_key)

    def prepare(self, row):
        return row

    def read(self, row):
        self.events.append(("read", row.listing_id))
        return len(self.events)

    def judge(self, row, evidence):
        self.events.append(("judge", row.listing_id))
        return replace(item(self.key(row), row.price), loggable=True)

    def append(self, pairs):
        self.events.append(("append", [row.listing_id for row, _ in pairs]))

    def card(self, assessment):
        return Card(assessment.key, "https://example.test", "$10", "NOTICE", "Look", "Evidence")

    def report(self, buys, others, problems):
        return Report("Subject", "Heading", "Summary", "Footer",
                      tuple(self.card(value) for value in buys),
                      tuple(self.card(value) for value in others), tuple(problems))

    def persist(self):
        self.saved = True

    def close(self):
        self.closed = True


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.state = AlertState(self.path / "alerts.json", normalise_key)
        self.options = RunOptions(Bands.NOTICE, Bands.NOTICE, Improvement(.011),
                                  preview=self.path / "preview.html")

    def test_steam_realert_table(self):
        self.state.record([item(price=10)], "email", NOW)
        cases = [
            (10, Bands.NOTICE, 0, False),
            (9.99, Bands.NOTICE, 0, False),
            (9.989, Bands.NOTICE, 0, False),
            (9.988, Bands.NOTICE, 0, True),
            (10, Bands.NOTICE, 30 * 86400, False),
            (10, Bands.NOTICE, 30 * 86400 + 1, True),
            (20, Bands.NOTICE, 0, False),
        ]
        for price, verdict, age, expected in cases:
            with self.subTest(price=price, age=age):
                self.assertEqual(self.state.is_new(item(price=price, verdict=verdict), "email",
                    Improvement(.011), 30, NOW + timedelta(seconds=age)), expected)
        self.state.record([item(verdict=Bands.SKIP)], "email", NOW)
        self.assertTrue(self.state.is_new(item(price=20), "email", Improvement(.011), 30, NOW))

    def test_hardware_four_percent_not_a_dollar(self):
        policy = Improvement(1.01, 4)
        for old, new, expected in [(100, 96, True), (100, 96.01, False),
                                   (1000, 998, False), (0, 0, False)]:
            with self.subTest(old=old, new=new):
                self.assertEqual(policy.better(new, 1, old, 1), expected)

    def test_receipts_are_per_transport_and_per_price_baseline(self):
        self.state.record([item(price=100)], "email", NOW)
        self.state.record([item(price=95)], "ntfy", NOW)
        self.assertTrue(self.state.is_new(item(price=95), "email", Improvement(.011), 30, NOW))
        self.assertFalse(self.state.is_new(item(price=95), "ntfy", Improvement(.011), 30, NOW))

    def test_failed_send_is_retried_without_repeating_successful_channel(self):
        email, push = Mock(), Mock(side_effect=RuntimeError("no network"))
        channels = (Channel("ntfy", "push", push), Channel("email", "email", email))
        result = run(Domain([listing()]), self.state, self.options, channels, now=NOW)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(set(self.state.records["test:a"]), {"email"})
        loaded = AlertState(self.state.path, normalise_key)
        retry = Mock()
        options = replace(self.options, quiet_when_empty=True)
        run(Domain([listing()]), loaded, options,
            (Channel("ntfy", "push", retry), Channel("email", "email", email)), now=NOW)
        self.assertEqual(email.call_count, 1)
        self.assertEqual(retry.call_count, 1)
        self.assertEqual(set(loaded.records["test:a"]), {"email", "ntfy"})

    def test_failed_source_does_not_erase_or_block_other_sources(self):
        self.state.record([item("dead:x")], "email", NOW)
        domain = Domain([listing()], complete=True)
        domain.sources += (SimpleNamespace(name="dead", fetch=Mock(side_effect=SourceError("offline"))),)
        send = Mock()
        result = run(domain, self.state, self.options, (Channel("email", "email", send),), now=NOW)
        self.assertEqual(len(result.assessments), 1)
        self.assertIn("dead:x", self.state.records)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(domain.closed)

    def test_partial_empty_does_not_mean_gone_but_complete_empty_does(self):
        for complete in (False, True):
            self.state.record([item()], "email", NOW)
            run(Domain([], complete=complete), self.state, self.options, (), now=NOW)
            self.assertEqual("test:a" in self.state.records, not complete)

    def test_history_failure_keeps_raw_identity_live(self):
        self.state.record([item()], "email", NOW)
        domain = Domain([listing()], complete=True)
        domain.history = DelegatedHistory(Mock(side_effect=SourceError("history unavailable")))
        result = run(domain, self.state, self.options, (), now=NOW)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("test:a", self.state.records)

    def test_all_source_failures_do_not_write_state(self):
        domain = Domain([])
        domain.sources[0].fetch = Mock(side_effect=SourceError("offline"))
        self.assertEqual(run(domain, self.state, self.options, (), now=NOW).exit_code, 1)
        self.assertFalse(self.state.path.exists())
        self.assertFalse(domain.saved)
        self.assertTrue(domain.closed)

    def test_entire_cohort_judged_before_any_append(self):
        domain = Domain([listing("a"), listing("b")], accumulated=True)
        run(domain, self.state, self.options, (), now=NOW)
        self.assertEqual(domain.events, [("read", "a"), ("judge", "a"),
            ("read", "b"), ("judge", "b"), ("append", ["a", "b"])])

    def test_source_veto_and_variants_cannot_be_overridden_by_judgment(self):
        domain = Domain([listing("a", loggable=False), listing("b", multi_variant=True),
                         listing("c")], accumulated=True)
        result = run(domain, self.state, self.options, (), now=NOW)
        self.assertEqual(len(result.assessments), 3)
        self.assertEqual(domain.events[-1], ("append", ["c"]))

    def test_dry_run_only_writes_preview(self):
        self.state.record([item()], "email", NOW)
        self.state.save(NOW)
        before = self.state.path.read_bytes()
        domain, send = Domain([listing("b")], accumulated=True), Mock()
        run(domain, self.state, replace(self.options, dry_run=True),
            (Channel("email", "email", send),), now=NOW)
        self.assertEqual(before, self.state.path.read_bytes())
        self.assertTrue(self.options.preview.exists())
        self.assertNotIn("append", [event[0] for event in domain.events])
        self.assertFalse(domain.saved)
        self.assertTrue(domain.closed)
        send.assert_not_called()

    def test_force_bypasses_suppression_not_hard_veto(self):
        self.state.record([item()], "email", NOW)
        send = Mock()
        run(Domain([listing()]), self.state, replace(self.options, force=True),
            (Channel("email", "email", send),), now=NOW)
        self.assertEqual(send.call_count, 1)
        self.assertFalse(qualifies(replace(item(), alertable=False, target_override=True), Bands.SKIP))

    def test_no_shared_vocabulary_or_fixed_axes(self):
        class Other(IntEnum):
            BUY = 17
        self.assertTrue(qualifies(item(), Bands.NOTICE))
        with self.assertRaises(TypeError):
            qualifies(item(), Other.BUY)
        domain = Domain([listing()])
        domain.axes = ("price", "value", "utility")
        domain.judge = lambda row, evidence: replace(item(), axes=tuple((axis, axis) for axis in domain.axes))
        self.assertEqual(len(run(domain, self.state, self.options, (), now=NOW).assessments), 1)

    def test_legacy_shapes_and_collapsed_variations_migrate(self):
        data = {"alerts": {
            "ebay:v1|123|111": {"price": 650, "verdict": 4, "pushed_at": NOW.isoformat()},
            "ebay:v1|123|222": {"price": 600, "verdict": 3,
                               "digested_at": (NOW + timedelta(seconds=1)).isoformat()},
        }}
        self.state.path.write_text(json.dumps(data))
        loaded = AlertState(self.state.path, normalise_key)
        self.assertEqual(set(loaded.records), {"ebay:v1|123"})
        self.assertEqual(loaded.records["ebay:v1|123"]["email"].price, 600)
        self.assertEqual(loaded.records["ebay:v1|123"]["ntfy"].price, 650)
        self.state.path.write_text(json.dumps({"alerts": {"220": {
            "price": 9.99, "verdict": 5, "alerted_at": NOW.isoformat()}}}))
        from alerters.steam.plugin import SteamPlugin
        steam = AlertState(self.state.path, SteamPlugin.normalise_key)
        from alerters.steam.judgment import Verdict
        self.assertFalse(steam.is_new(item("steam:220", 9.99, Verdict.ALL_TIME_LOW),
                                     "email", Improvement(.011), 30, NOW))

    def test_corrupt_state_is_not_silently_reset(self):
        self.state.path.write_text("not JSON")
        with self.assertRaises(ValueError):
            AlertState(self.state.path, normalise_key)

    def test_group_id_and_dedupe_keep_cheapest_without_laundering(self):
        rows = [listing("v1|123|1", source="ebay", price=700, loggable=False),
                listing("v1|123|2", source="ebay", price=600, multi_variant=True),
                listing("v1|123|3", source="ebay", price=None)]
        found = dedupe(rows, Domain.key)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].price, 600)
        self.assertFalse(found[0].loggable)
        self.assertTrue(found[0].multi_variant)
        self.assertEqual(group_id("ordinary-id"), "ordinary-id")
        self.assertEqual(group_id("v1|123|abc"), "v1|123|abc")
