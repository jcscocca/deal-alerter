"""The alert band and the bait band must not describe the same price.

Both are ratios against the same anchor, and on 2026-08-17 they had quietly
collapsed onto each other. `suspicious_price_ratio` was 0.5 and the reference
path called anything at or under 0.60 EXCEPTIONAL, so a listing between those
two numbers was simultaneously the best verdict the tool could give and a price
it refused to record. Every alert the tool had ever produced sat in that gap.

Nothing in the code said the bands had to stay apart, so nothing noticed. That
is what this file is for. It asserts the ordering rather than the constants, so
retuning stays possible and collapsing them does not.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from alerters.hardware.native.config import ROOT, Thresholds, _thresholds_from

TH = Thresholds()


class TestBandsStayDisjoint:
    def test_bait_floor_sits_below_the_best_verdict(self) -> None:
        """The invariant. A price good enough to be the tool's top call must be
        one it is also willing to believe."""
        assert TH.suspicious_price_ratio < TH.reference_grail_ratio

    def test_bands_are_ordered_worst_to_best(self) -> None:
        assert (
            TH.reference_grail_ratio
            < TH.reference_exceptional_ratio
            < TH.reference_strong_ratio
            < TH.reference_good_ratio
            < TH.reference_fair_ratio
        )

    def test_bait_floor_sits_above_the_hard_reject(self) -> None:
        """Below min_price_ratio a listing is dropped outright, so a bait floor
        at or under it would leave the shown-but-never-logged band empty."""
        assert TH.min_price_ratio < TH.suspicious_price_ratio


class TestAlertBandIsReachable:
    """A threshold no honest listing can reach filters for broken data.

    Measured over the committed log on 2026-08-17: asking prices ran at a
    median of 1.50x their sold-based reference and the 1st percentile was
    0.91x, while the STRONG line sat at 0.75x. Four of 1,417 observations
    cleared it and all four were bait or mismatches. The alert band has to
    overlap the distribution it is filtering.
    """

    def test_strong_is_reachable_by_a_real_asking_price(self) -> None:
        # The observed 1st percentile. Something at the very bottom of the
        # honest ask distribution should be able to earn an alert.
        assert TH.reference_strong_ratio > 0.91

    def test_the_typical_asking_price_still_does_not_alert(self) -> None:
        # ...and the median ask, which is 1.50x, must not.
        assert TH.reference_strong_ratio < 1.50


class TestConfigLoaderHonoursDefaults:
    """The loader used to retype every default as a literal, and they drifted.

    config.toml sets neither suspicious_price_ratio nor
    reference_max_price_ratio, so the loader's own 0.5 and 3.0 were what ran
    while the dataclass said 0.5 and 2.0. Editing the dataclass appeared to
    work and changed nothing.
    """

    def test_absent_keys_fall_back_to_the_dataclass(self) -> None:
        loaded = _thresholds_from({})
        assert loaded == Thresholds()

    def test_present_keys_win(self) -> None:
        loaded = _thresholds_from({"suspicious_price_ratio": 0.42})
        assert loaded.suspicious_price_ratio == 0.42

    def test_int_fields_stay_int(self) -> None:
        loaded = _thresholds_from({"min_observations": 12})
        assert loaded.min_observations == 12
        assert isinstance(loaded.min_observations, int)

    def test_shipped_config_does_not_reintroduce_an_overlap(self) -> None:
        """The invariant has to hold for the config actually shipped, not just
        for the defaults."""
        with (ROOT / "config.toml").open("rb") as handle:
            section = tomllib.load(handle).get("thresholds", {})
        shipped = _thresholds_from(section)
        assert shipped.suspicious_price_ratio < shipped.reference_grail_ratio
