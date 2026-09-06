"""What may reach your eyes, and what may reach the price log.

These are different questions and the tool answers them separately. You can
judge a suspicious listing better than a threshold can, so risky listings are
still shown -- but the distribution every future verdict is measured against
only accepts prices it has reason to trust. A scam price you glance at and
dismiss costs you thirty seconds; the same price in the log quietly skews every
verdict for that part from then on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from alerters.hardware.native.config import Config
from alerters.hardware.native.history import History, bucket_for
from alerters.hardware.native.sources.base import Listing
from alerters.hardware.native.sources.ebay import _seller_risk
from alerters.hardware.native.verdict import Verdict
from check_deals import evaluate, price_stats


@pytest.fixture
def cfg(monkeypatch) -> Config:
    for name, value in (
        ("SMTP_USER", "nobody@example.invalid"),
        ("SMTP_PASSWORD", "unused"),
        ("MAIL_TO", "nobody@example.invalid"),
    ):
        monkeypatch.setenv(name, value)
    return Config.load()


@pytest.fixture
def history(tmp_path):
    store = History(tmp_path / "prices.db")
    yield store
    store.close()


def _listing(**overrides) -> Listing:
    base = dict(
        listing_id="l1",
        source="ebay",
        title="EVGA RTX 3090 FTW3 24GB",
        url="https://example.invalid/3090",
        posted_at=datetime.now(timezone.utc),
        price=700.0,
    )
    base.update(overrides)
    return Listing(**base)


class TestParts:
    def test_parts_never_pools_with_working_cards(self) -> None:
        assert bucket_for("parts") == "parts"

    def test_a_for_parts_card_is_shown_but_not_logged(
        self, cfg: Config, history: History
    ) -> None:
        """It already scored PASS; the danger was it becoming the used low."""
        assessments, _ = evaluate(
            cfg, [_listing(price=300.0, condition_hint="parts")], history
        )
        assert assessments[0].verdict is Verdict.PASS
        assert history.total_observations() == 0


class TestSamplingBias:
    def test_price_sorted_ebay_actives_are_not_logged(
        self, cfg: Config, history: History
    ) -> None:
        evaluate(cfg, [_listing(loggable=False)], history)
        assert history.total_observations() == 0

    def test_confirmed_sales_are_logged(self, cfg: Config, history: History) -> None:
        evaluate(cfg, [_listing(source="ebay-sold", sold=True)], history)
        assert history.total_observations() == 1


class TestSuspiciousPrice:
    def test_far_below_market_is_shown_but_not_logged(
        self, cfg: Config, history: History
    ) -> None:
        """$300 against a $750 reference is ratio 0.40 -- the scam band.

        It clears min_price_ratio (0.25) deliberately: a genuine steal lives in
        the same band, and price alone cannot separate the two.
        """
        assessments, _ = evaluate(cfg, [_listing(price=300.0)], history)
        assert assessments, "must still be surfaced for your judgment"
        assert "bait rather than a bargain" in assessments[0].reason
        assert history.total_observations() == 0

    def test_an_ordinary_price_is_logged(self, cfg: Config, history: History) -> None:
        evaluate(cfg, [_listing(price=700.0)], history)
        assert history.total_observations() == 1


class TestSellerRisk:
    @pytest.mark.parametrize(
        "item, expected",
        [
            ({"seller": {"feedbackScore": 4200, "feedbackPercentage": "99.8"}}, "low"),
            ({"seller": {"feedbackScore": 3, "feedbackPercentage": "100.0"}}, "high"),
            ({"seller": {"feedbackScore": 30, "feedbackPercentage": "99.0"}}, "moderate"),
            ({"seller": {"feedbackScore": 900, "feedbackPercentage": "91.0"}}, "high"),
            ({"itemLocation": {"country": "CN"}}, "moderate"),
            ({}, "low"),
        ],
    )
    def test_grading(self, item: dict, expected: str) -> None:
        assert _seller_risk(item)[0] == expected

    def test_missing_seller_data_is_not_treated_as_risk(self) -> None:
        """Absent fields mean eBay didn't send them, not that the seller is bad."""
        assert _seller_risk({"seller": {}}) == ("low", "")

    def test_high_risk_downgrades_and_blocks_logging(
        self, cfg: Config, history: History
    ) -> None:
        clean, _ = evaluate(cfg, [_listing(price=700.0)], history)
        risky, _ = evaluate(
            cfg,
            [
                _listing(
                    listing_id="l2",
                    price=700.0,
                    seller_risk="high",
                    seller_note="the seller has 3 feedback",
                )
            ],
            history,
        )
        assert risky[0].verdict < clean[0].verdict
        assert "3 feedback" in risky[0].reason
        # Only the clean listing made it into the log.
        assert history.total_observations() == 1


class TestUntrustedSellerAtAnAlertingPrice:
    """The 2026-08-17 incident, end to end.

    eBay listing 206497757350: a Mac Studio M3 Ultra 256GB at $4,996 against a
    $9,762 sold average, from an account with no feedback opened that same
    month, its condition field contradicting its own title. It cleared the bait
    floor by about $115, scored EXCEPTIONAL against the reference, took a single
    downgrade for the seller -- and landed on STRONG, which is exactly the
    digest threshold. It arrived by email.

    One level is the wrong instrument here. An untrusted seller and a
    suspiciously good price are not two independent discounts to apply, they
    are one profile, and the listing has to fall clear of the alert floor
    rather than onto it.
    """

    TITLE = "Apple Mac Studio 2025 M3 Ultra 28C/60C 256GB RAM 2TB SSD | A3389"

    def test_the_mac_studio_does_not_reach_the_digest(
        self, cfg: Config, history: History
    ) -> None:
        items, _ = evaluate(
            cfg,
            [
                _listing(
                    listing_id="206497757350",
                    title=self.TITLE,
                    price=4996.0,
                    seller_risk="high",
                    seller_note="the seller has 0 feedback",
                )
            ],
            history,
        )
        assert items, "the listing must still be matched and shown"
        assert items[0].verdict <= Verdict.GOOD, "must not reach the digest floor"
        assert not items[0].loggable
        assert history.total_observations() == 0

    def test_an_ordinary_price_from_the_same_seller_only_drops_one_level(
        self, cfg: Config, history: History
    ) -> None:
        """The cap is aimed at the profile, not at new sellers generally. A
        merely unremarkable price keeps the old one-level treatment."""
        clean, _ = evaluate(
            cfg, [_listing(listing_id="a", title=self.TITLE, price=13000.0)], history
        )
        risky, _ = evaluate(
            cfg,
            [
                _listing(
                    listing_id="b",
                    title=self.TITLE,
                    price=13000.0,
                    seller_risk="high",
                    seller_note="the seller has 0 feedback",
                )
            ],
            history,
        )
        assert risky[0].verdict == Verdict(max(int(clean[0].verdict) - 1, 0))
        assert "Downgraded one level" in risky[0].reason


class TestSoldPricesDoNotPoolWithAsking:
    def test_asking_prices_are_used_until_there_are_enough_sales(
        self, cfg: Config, history: History
    ) -> None:
        for index in range(10):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=900.0,
                source="reddit",
                listing_id=f"ask-{index}",
            )
        history.commit()
        stats = price_stats(history, "rtx_3090", "used", cfg.thresholds)
        assert stats.count == 10
        assert stats.median == 900.0

    def test_confirmed_sales_take_over_once_trustworthy(
        self, cfg: Config, history: History
    ) -> None:
        # Spread over months: percentiles need time depth, not just row count,
        # or one snapshot of current inventory would rank against itself.
        now = datetime.now(timezone.utc)
        for index in range(10):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=900.0,
                source="reddit",
                listing_id=f"ask-{index}",
                seen_at=now - timedelta(days=90 - index * 3),
            )
        for index in range(8):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=700.0,
                source="ebay-sold",
                listing_id=f"sold-{index}",
                sold=True,
                seen_at=now - timedelta(days=80 - index * 5),
            )
        history.commit()

        stats = price_stats(history, "rtx_3090", "used", cfg.thresholds)
        assert stats.count == 8, "asking prices must not dilute the sold sample"
        assert stats.median == 700.0
