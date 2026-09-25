"""HARDWARE_SOURCES picks which sources a run fetches.

Reddit's anonymous RSS is throttled hard and was ~80% of a run, so the
15-minute push loop runs without it and Reddit gets its own hourly loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alerters.hardware.native.config import Config
from alerters.hardware.native.sources import build_sources

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load(monkeypatch, sources: str | None, *, ebay: bool = True) -> Config:
    for name in ("HARDWARE_SOURCES", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    if sources is not None:
        monkeypatch.setenv("HARDWARE_SOURCES", sources)
    if ebay:
        monkeypatch.setenv("EBAY_CLIENT_ID", "id")
        monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    return Config.load(CONFIG / "hardware.toml", CONFIG / "watchlist.toml")


def names(cfg: Config) -> list[str]:
    return [source.name for source in build_sources(cfg)]


def test_unset_runs_every_source(monkeypatch) -> None:
    assert names(load(monkeypatch, None)) == ["reddit", "slickdeals", "apple-refurb", "ebay"]


def test_the_fast_loop_leaves_reddit_out(monkeypatch) -> None:
    cfg = load(monkeypatch, "ebay, slickdeals,apple-refurb")
    assert names(cfg) == ["slickdeals", "apple-refurb", "ebay"]


def test_the_reddit_loop_runs_reddit_alone(monkeypatch) -> None:
    assert names(load(monkeypatch, "reddit")) == ["reddit"]


def test_a_misspelt_source_fails_loudly(monkeypatch) -> None:
    # A typo would otherwise run nothing, every 15 minutes, in silence.
    with pytest.raises(ValueError, match="redit"):
        build_sources(load(monkeypatch, "redit"))


def test_naming_ebay_without_its_keys_still_sits_it_out(monkeypatch) -> None:
    assert names(load(monkeypatch, "ebay", ebay=False)) == []
