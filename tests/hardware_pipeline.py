"""Drive the real hardware pipeline over listings built by hand.

The tests inherited from ai-deal-alerter were written against `evaluate()` and
`price_stats()`, free functions in its retired `check_deals` entry point. That
orchestration now lives in `dealcore.run` and the plugin's prepare, history
read and judge, so these helpers run exactly that code -- the shipped config
and watchlist, the native matcher and verdict engine -- with a stub in place
of the network.

What a run leaves behind is read back the way the next run would read it: from
the persisted JSONL. The SQLite database is private to a single run now, so
the committed log is the only thing a later verdict can be measured against.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from alerters.hardware.plugin import HardwarePlugin
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

CONFIG = Path(__file__).resolve().parents[1] / "config" / "hardware.toml"


class StubSource:
    name = "stub"

    def __init__(self, listings: list[Listing]) -> None:
        self.listings = listings

    def fetch(self) -> FetchResult:
        return FetchResult(list(self.listings))


def plugin(state_root: Path) -> HardwarePlugin:
    """A plugin over the shipped configuration and whatever log is in state_root."""
    return HardwarePlugin(CONFIG, state_root)


def evaluate(state_root: Path, listings: list[Listing], *, record: bool = True):
    """One run over these listings. Returns (assessments, matched count).

    `record=False` is a dry run. Each assessment is the native one carrying the
    run's final verdict, because that verdict -- after the adapter's no-upgrade
    cap -- is the one an alert floor is compared with.
    """
    hardware = plugin(state_root)
    hardware.sources = (StubSource(listings),)
    state = AlertState(hardware.state_dir / "alerts.json", hardware.normalise_key)
    options = replace(hardware.options, dry_run=not record,
                      preview=state_root / "report-hardware.html")
    result = run(hardware, state, options, ())
    assert not result.problems, result.problems
    return [replace(item.detail, verdict=item.verdict) for item in result.assessments], hardware.matched


def logged(state_root: Path) -> int:
    """Observations the next run would load from the persisted log."""
    hardware = plugin(state_root)
    try:
        return hardware.log.total_observations()
    finally:
        hardware.close()
