"""Prebuilts asking less than the cheapest loose card they contain.

Everywhere else in this plugin a whole machine is refused as evidence: its
price describes a computer, not the GPU inside it, so `is_system` keeps it out
of the price log. The comparison here runs the other way -- loose cards are the
evidence and the machine is the candidate -- so the refusal is untouched and
nothing new is recorded.

The rules worth protecting are the ones that stop this inventing an
opportunity: only prices the run was willing to log count as the benchmark,
and a comparison across different conditions says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace as NS

from alerters.hardware.plugin import HardwarePlugin
from dealcore.types import Assessment


@dataclass(frozen=True)
class Detail:
    unit_price: float
    condition: str = "used"
    is_system: bool = False
    is_bundle: bool = False
    multi_variant: bool = False
    title: str = ""
    part: NS = field(default_factory=lambda: NS(key="rtx_3090", name="RTX 3090 24GB"))


def row(key: str, price: float, *, loggable: bool = True, **detail) -> Assessment:
    return Assessment(key, price, 0, Detail(unit_price=price, **detail), loggable=loggable)


def signals(*rows: Assessment) -> dict[str, str]:
    plugin = HardwarePlugin.__new__(HardwarePlugin)
    plugin.verdict = NS(DOLLAR=1.01)
    return plugin.arbitrage(list(rows))


class TestTheSignalFires:
    def test_a_machine_under_the_cheapest_loose_card(self) -> None:
        found = signals(row("pc", 500, is_system=True), row("card", 700))
        assert set(found) == {"pc"}
        assert "$200 of room" in found["pc"]
        assert "Same condition on both sides" in found["pc"]

    def test_the_cheapest_card_sets_the_bar_not_the_first_one(self) -> None:
        assert signals(row("pc", 500, is_system=True), row("a", 900), row("b", 700))
        # 400 is under the machine, so parting it out buys nothing.
        assert not signals(row("pc", 500, is_system=True), row("a", 900), row("b", 400))

    def test_a_dearer_machine_is_not_an_opportunity(self) -> None:
        assert not signals(row("pc", 900, is_system=True), row("card", 700))

    def test_a_dollar_of_daylight_is_not_an_opportunity(self) -> None:
        assert not signals(row("pc", 700, is_system=True), row("card", 700.5))


class TestWhatCannotBeTheBenchmark:
    def test_an_untrusted_price_is_not_a_price(self) -> None:
        # A bait listing is shown but never logged. Letting it set the
        # benchmark would either invent an opportunity or bury a real one.
        assert not signals(row("pc", 500, is_system=True), row("bait", 700, loggable=False))

    def test_a_machine_is_never_measured_against_another_machine(self) -> None:
        assert not signals(row("pc", 500, is_system=True), row("other", 700, is_system=True))

    def test_bundles_and_unidentified_options_are_not_prices_either(self) -> None:
        assert not signals(row("pc", 500, is_system=True), row("lot", 700, is_bundle=True))
        assert not signals(row("pc", 500, is_system=True), row("opt", 700, multi_variant=True))

    def test_a_different_gpu_is_a_different_comparison(self) -> None:
        other = NS(key="rtx_4090", name="RTX 4090 24GB")
        assert not signals(row("pc", 500, is_system=True), row("card", 700, part=other))


class TestConditionHonesty:
    def test_a_cross_condition_comparison_is_marked_potential(self) -> None:
        found = signals(row("pc", 500, is_system=True, condition="used"),
                        row("card", 700, condition="new"))
        assert "Potential only" in found["pc"]

    def test_same_condition_is_preferred_over_a_cheaper_mismatch(self) -> None:
        # The $600 new card is cheaper, but a used machine against a new card
        # is not like for like; the $650 used one is the honest benchmark.
        found = signals(row("pc", 500, is_system=True, condition="used"),
                        row("new", 600, condition="new"),
                        row("used", 650, condition="used"))
        assert "$150 of room" in found["pc"]
        assert "Same condition on both sides" in found["pc"]

    def test_an_unstated_condition_cannot_claim_a_match(self) -> None:
        found = signals(row("pc", 500, is_system=True, condition="unknown"),
                        row("card", 700, condition="unknown"))
        assert "Potential only" in found["pc"]


WORKSTATION = NS(key="rtx_pro_6000_blackwell", name="RTX PRO 6000 Blackwell Workstation")
MAXQ = NS(key="rtx_pro_6000_blackwell_maxq", name="RTX PRO 6000 Blackwell Max-Q")


class TestAnUnnamedEditionIsNotTheWorkstationCard:
    def test_a_prebuilt_that_never_names_the_edition_is_held_to_the_max_q(self) -> None:
        # eBay 377092731100, seen 2026-09-24: the VRLA Tech box held a Max-Q
        # per its item specifics, and loose new Max-Qs were at $15,000.
        found = signals(
            row("pc", 16919.96, is_system=True, condition="new", part=WORKSTATION,
                title="Intel Core Ultra 7 265K RTX PRO 6000 Blackwell 32GB DDR5 Workstation for Enscape"),
            row("ws", 17000, condition="new", part=WORKSTATION,
                title="NVIDIA RTX PRO 6000 Blackwell Workstation Edition 96GB GDDR7"),
            row("mq", 14999.99, condition="new", part=MAXQ,
                title="New NVIDIA RTX PRO 6000 Blackwell Max-Q 96GB GDDR7 Graphics Card PG153B"),
        )
        assert not found

    def test_a_prebuilt_that_names_the_workstation_edition_keeps_the_headline(self) -> None:
        for title in ("RTX PRO 6000 Blackwell Workstation Edition 96GB Threadripper Workstation",
                      "Threadripper 9970X RTX PRO 6000 Blackwell 600W 96GB Workstation"):
            found = signals(
                row("pc", 16000, is_system=True, condition="new", part=WORKSTATION, title=title),
                row("ws", 17000, condition="new", part=WORKSTATION,
                    title="NVIDIA RTX PRO 6000 Blackwell Workstation Edition 96GB GDDR7"),
                row("mq", 14999.99, condition="new", part=MAXQ,
                    title="New NVIDIA RTX PRO 6000 Blackwell Max-Q 96GB GDDR7 Graphics Card PG153B"),
            )
            assert "$1,000 of room" in found["pc"]
            assert "RTX PRO 6000 Blackwell Workstation this run" in found["pc"]
