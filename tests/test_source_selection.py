"""HARDWARE_SOURCES picks which sources a run fetches.

The fast loop uses the selected Reddit scope, defaulting to retail deals.
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


def test_a_source_filter_can_leave_reddit_out(monkeypatch) -> None:
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


def test_reddit_subs_can_be_narrowed(monkeypatch) -> None:
    monkeypatch.setenv("REDDIT_SUBS", " customdeals, buildapcsales ")
    cfg = load(monkeypatch, "reddit")
    assert build_sources(cfg)[0].subreddits == ("customdeals", "buildapcsales")


def test_reddit_subs_default_to_selected_retail_scope(monkeypatch) -> None:
    monkeypatch.delenv("REDDIT_SUBS", raising=False)
    assert load(monkeypatch, None).reddit_subs == ("buildapcsales",)
