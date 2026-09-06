"""Golden table generated from the supplied, verbatim sda/verdict.py.

Set LEGACY_STEAM_VERDICT to that actual file to compare full results directly,
not just the frozen hashes. No old repository is needed for the normal suite.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import types
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from alerters.steam import judgment as new
from alerters.steam.config import Thresholds
from alerters.steam.sources import Deal, GamePrices, HistoryPoint, Money, StoreLow
from dealcore.verdict import ago

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def original(path: Path):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    # Only type imports are redirected. Every decision and sentence remains the
    # original source, executed in its own module with its own frozen clock.
    tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and node.level)]
    module = types.ModuleType("_original_steam_verdict")
    sys.modules[module.__name__] = module
    module.__dict__.update(Thresholds=Thresholds, GamePrices=GamePrices,
                           HistoryPoint=HistoryPoint, StoreLow=StoreLow)
    exec(compile(tree, str(path), "exec"), module.__dict__)
    module.datetime = Clock
    return module


def inputs(**changes) -> dict:
    values = dict(price=11, cut=50, low=10, embedded=None, year=None, history="normal",
                  target=None, thresholds={}, symbol="$", has_deal=True)
    values.update(changes)
    currency = "EUR" if values["symbol"] == "€" else "USD"
    m = lambda value: Money(value, currency)
    points = [(500, 40, 0), (400, 10, 75), (395, 40, 0), (100, 12, 70), (95, 40, 0)]
    if values["history"] == "empty":
        points = []
    elif values["history"] == "ongoing":
        points += [(0, values["price"], values["cut"])]
    elif values["history"] == "stale_dip":
        points += [(10, values["price"], values["cut"])]
    elif values["history"] == "recently_ended":
        # Preserve the legacy heuristic, including its recently-ended-sale quirk.
        points += [(1, values["price"], values["cut"]), (0, 40, 0)]
    return dict(appid=220, title="Golden game", boxart=None,
        prices=GamePrices("golden", Deal(m(values["price"]), m(40), values["cut"],
            store_low=m(values["embedded"]) if values["embedded"] is not None else None)
            if values["has_deal"] else None, low_all=m(8),
            low_y1=m(values["year"]) if values["year"] is not None else None),
        store_low=StoreLow(m(values["low"]), NOW-timedelta(days=730), 75)
            if values["low"] is not None else None,
        history=[HistoryPoint(NOW-timedelta(days=days), price, cut) for days, price, cut in points],
        thresholds=replace(Thresholds(), **values["thresholds"]),
        target_price=values["target"], symbol=values["symbol"])


def serial(item):
    return None if item is None else json.loads(json.dumps(asdict(item), default=lambda x: x.isoformat(), sort_keys=True))


def digest(item) -> str:
    return hashlib.sha256(json.dumps(serial(item), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# name, input changes, expected band, SHA256 of the complete legacy assessment.
CASES = [
    ('no deal', {'has_deal': False}, None, '74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b'),
    ('no benchmark wait', {'history': 'empty', 'low': None, 'cut': 49}, 'WAIT', '9efcf37245691c9b9a42ba5099dca71ee0223bae84a1eaf0f5f81f8517a4732e'),
    ('no benchmark decent', {'history': 'empty', 'low': None, 'cut': 50}, 'DECENT', '20c27a811d1360e1f6fb27acea03db8e2cb279f9d15d583795ae849ec55c6f87'),
    ('first discount is not a record', {'history': 'empty', 'price': 10, 'cut': 75}, 'DECENT', 'e5f36e48fa0ef7c6d266db9f2877eed8f42f7df65fed9187db306b5235247f52'),
    ('all-time lower', {'price': 9}, 'ALL_TIME_LOW', 'cd72f0e4dc59cabe677ab3b20156a28d5e6296f0d8b9e153f82678cf3373eb1c'),
    ('all-time equal', {'price': 10}, 'ALL_TIME_LOW', '6644050b228efd2b94392c07e6dfa502388d48075a8b6430be2086ba18ac4dd7'),
    ('absolute epsilon equal', {'price': 10.011}, 'ALL_TIME_LOW', '3d9abf7a0949084095ae1a6099d03de120695a464c323d22654d7427cb8570d3'),
    ('outside absolute epsilon', {'price': 10.012}, 'MATCHES_LOW', '4b1ef023c9fad222a642c7ab7b8012b99da02cb94648357cbd346d9fbabeb21f'),
    ('matches percent boundary', {'price': 10.2}, 'MATCHES_LOW', 'cb8f91f1c6a4bbf866115030ceea0f09cec57c724f9c9a5f8d95b08dde6e04fb'),
    ('outside matches boundary', {'price': 10.201}, 'NEAR_LOW', '05e80e6e0838e2fb89cf2283dee47a5db6e0f27e50388d481f3fcc2a993f0113'),
    ('near percent boundary', {'price': 11}, 'NEAR_LOW', '71f46a6e29592e3bec8961e97d6e2004d278e03687a1b6ba83d4eb14756438b4'),
    ('outside near boundary', {'price': 11.001, 'cut': 49}, 'WAIT', 'd0f3fb94188b7412e16985d3cfed32c1c99c29a55f15ebac99b6881b77a515d9'),
    ('year boundary', {'price': 12.24, 'year': 12, 'cut': 49}, 'BEST_THIS_YEAR', '3290282512d0020df452c5ef2ab8bea34ddabad306ca56fd2927ae710d471769'),
    ('outside year boundary', {'price': 12.241, 'year': 12, 'cut': 49}, 'WAIT', '4e3ffc7776447d6862ac483e0214dae0c19d6f4987d98873cc5d46b61dc065c2'),
    ('deep but not low', {'price': 20, 'cut': 50}, 'DECENT', '78a64d3587390fae687afaf789c45da70c8fdb2cafcbe1986fdc90d187ffafde'),
    ('shallow and expensive', {'price': 20, 'cut': 49}, 'WAIT', '1fba495d98b9378ef52faca2afe8ab3c736e5c2c1c5fdbd3e1f921359e7e9d13'),
    ('embedded low fallback', {'low': None, 'embedded': 10, 'price': 10}, 'ALL_TIME_LOW', '0de4a02512e634517aa6b7fcc464755ea89f53d12c6795a7abc0bca81ce64339'),
    ('history low fallback', {'low': None, 'embedded': None, 'price': 10}, 'ALL_TIME_LOW', '0de4a02512e634517aa6b7fcc464755ea89f53d12c6795a7abc0bca81ce64339'),
    ('store low wins', {'low': 9, 'embedded': 10, 'price': 10}, 'DECENT', '74c68e2db3cf72c7e80217be9fd2b06bf42ba32cd7bd3831458ee9464eae3e5a'),
    ('ongoing excluded', {'price': 10, 'history': 'ongoing'}, 'ALL_TIME_LOW', '4be2a3089493f83c4b8491934c2a0e177b312afaf41df10466fe53e2f35f7dee'),
    ('stale dip counted', {'price': 10, 'history': 'stale_dip'}, 'ALL_TIME_LOW', 'bef8a3b90215878a54f70e23ab6d51fb0feb11aca4e0ae5e000551314dd7c47e'),
    ('recently ended legacy heuristic', {'price': 10, 'history': 'recently_ended'}, 'ALL_TIME_LOW', '4be2a3089493f83c4b8491934c2a0e177b312afaf41df10466fe53e2f35f7dee'),
    ('target boundary hit', {'price': 12.011, 'target': 12, 'cut': 49}, 'WAIT', '32fded9db3e11747cddb79a5ed184eba92973ece75bb0ea5adf6a06114982975'),
    ('target boundary missed', {'price': 12.012, 'target': 12, 'cut': 49}, 'WAIT', '265ab7322c663217fce9c0aa87250ffb6172ba09a780ab19b54e47483de4974b'),
    ('custom thresholds', {'price': 10.5, 'thresholds': {'matches_low_pct': 6.0, 'near_low_pct': 12.0}}, 'MATCHES_LOW', 'e464e30c9d06559430be12a7df13b2894f402b0dc199edd2dfbbfaddd5519c03'),
    ('custom year tolerance', {'price': 13, 'year': 12, 'thresholds': {'best_this_year_pct': 10.0}}, 'BEST_THIS_YEAR', 'b9e12c74bf2568d7f1f1e7820efa9a68189b590a52450aed4526278ae14e10c5'),
    ('custom first discount', {'history': 'empty', 'low': None, 'cut': 25, 'thresholds': {'decent_cut': 25}}, 'DECENT', '33021ce79348c1e9f07433bfc950d8d81c27d38fba18f7a956637bcae7c8b5a0'),
    ('currency and exact prose', {'price': 10.5, 'symbol': '€'}, 'NEAR_LOW', '19eea18156a69ad92bd22e0401bd467cc93a9d940d3f356129086d2d64511c98'),
]


class EquivalenceTests(unittest.TestCase):
    def test_table(self):
        legacy = original(Path(os.environ["LEGACY_STEAM_VERDICT"])) if os.environ.get("LEGACY_STEAM_VERDICT") else None
        with patch.object(new, "datetime", Clock), patch("dealcore.verdict.datetime", Clock):
            for name, changes, expected_band, expected_hash in CASES:
                with self.subTest(name=name):
                    item = new.assess(**inputs(**changes))
                    self.assertEqual(item.verdict.name if item else None, expected_band)
                    self.assertEqual(digest(item), expected_hash)
                    if legacy is not None:
                        self.assertEqual(serial(item), serial(legacy.assess(**inputs(**changes))))

    def test_ago_table(self):
        table = [(None, "at an unknown date"), (-1, "today"), (0, "today"), (1, "today"),
                 (2, "2 days ago"), (44, "44 days ago"), (45, "2 months ago"),
                 (329, "10 months ago"), (330, "about a year ago"), (474, "about a year ago"),
                 (475, "1.3 years ago"), (639, "1.7 years ago"), (640, "about 2 years ago"),
                 (730, "about 2 years ago"), (822, "2.3 years ago"), (1096, "about 3 years ago")]
        for days, expected in table:
            with self.subTest(days=days):
                self.assertEqual(ago(NOW-timedelta(days=days) if days is not None else None, now=NOW), expected)

    def test_threshold_defaults(self):
        self.assertEqual(asdict(Thresholds()), dict(matches_low_pct=2.0, near_low_pct=10.0,
                         best_this_year_pct=2.0, decent_cut=50, min_cut=10))

    def test_zero_low_legacy_failure_is_not_silently_rewritten(self):
        # Zero historical low (giveaway/100% off) must not divide by zero or
        # fall through into MATCHES_LOW. A 50% cut is DECENT; a 40% cut is WAIT.
        legacy = original(Path(os.environ["LEGACY_STEAM_VERDICT"])) if os.environ.get("LEGACY_STEAM_VERDICT") else None
        with patch.object(new, "datetime", Clock), patch("dealcore.verdict.datetime", Clock):
            item = new.assess(**inputs(low=0))
            self.assertIsNotNone(item)
            self.assertEqual(item.verdict.name, "DECENT")
            self.assertEqual(item.headline, "50% off, but record low was $0.00")
            self.assertIsNone(item.pct_above_low)
            if legacy is not None:
                self.assertEqual(serial(item), serial(legacy.assess(**inputs(low=0))))

            wait_item = new.assess(**inputs(low=0, cut=40))
            self.assertIsNotNone(wait_item)
            self.assertEqual(wait_item.verdict.name, "WAIT")
            self.assertEqual(wait_item.headline, "Wait -- record low was $0.00")
            self.assertIsNone(wait_item.pct_above_low)
            if legacy is not None:
                self.assertEqual(serial(wait_item), serial(legacy.assess(**inputs(low=0, cut=40))))

