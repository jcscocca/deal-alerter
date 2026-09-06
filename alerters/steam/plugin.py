"""The one-axis plugin: transport, delegated evidence, judgment, presentation."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dealcore.config import require_env
from dealcore.run import RunOptions
from dealcore.types import Assessment, Card, DelegatedHistory, Listing, Report
from dealcore.verdict import Improvement, band, money
from .config import Config, load_targets
from .history import Candidate, Evidence, SteamHistory
from .judgment import CENT, Verdict, assess
from .sources import ItadClient, SteamSource, TitleCache


class SteamPlugin:
    name, bands, axes, default_mode = "steam", Verdict, ("history",), "digest"

    def __init__(self, config_path: Path, state_root: Path, *, fixture: Path | None = None) -> None:
        self.cfg = Config.load(config_path)
        self.state_dir = state_root / self.name / self.cfg.general.country
        self.cache = TitleCache(self.state_dir / "games.json")
        self.targets = load_targets(config_path.with_name("steam-targets.json"))
        replay = json.loads(fixture.read_text(encoding="utf-8")) if fixture else None
        if replay is None:
            require_env("STEAM_ID", "ITAD_API_KEY")
        self.client = ItadClient(os.environ.get("ITAD_API_KEY", ""), self.cfg.general.country, replay=replay)
        self.source = SteamSource(self.client, os.environ.get("STEAM_ID", ""), self.cfg.thresholds.min_cut)
        self.sources = (self.source,)
        self.history = DelegatedHistory(SteamHistory(self.client, self.source, self.cfg.general.history_years).read)
        self.options = RunOptions(band(Verdict, self.cfg.alerts.alert_at), None,
                                  Improvement(CENT), self.cfg.alerts.remind_after_days)
        self.scored = 0

    @staticmethod
    def key(listing: Listing) -> str:
        return f"steam:{listing.listing_id}"

    @staticmethod
    def normalise_key(key: str) -> str:
        return key if key.startswith("steam:") else f"steam:{int(key)}"

    def prepare(self, listing: Listing) -> Candidate:
        game = listing.extra["prices"]
        meta = self.cache.get(game.itad_id)
        if meta is None:
            info = self.client.game_info(game.itad_id)
            meta = {"title": info.get("title") or listing.title,
                    "boxart": (info.get("assets") or {}).get("boxart")}
            self.cache.put(game.itad_id, meta["title"], meta["boxart"])
        appid = int(listing.listing_id)
        return Candidate(appid, meta["title"], meta.get("boxart"), game, self.targets.get(appid))

    def judge(self, candidate: Candidate, evidence: Evidence) -> Assessment | None:
        item = assess(appid=candidate.appid, title=candidate.title, boxart=candidate.boxart,
                      prices=candidate.prices, store_low=evidence.store_low, history=evidence.points,
                      thresholds=self.cfg.thresholds, target_price=candidate.target,
                      symbol=self.cfg.general.currency_symbol)
        if item is None:
            return None
        self.scored += 1
        return Assessment(f"steam:{item.appid}", item.price, item.verdict, item,
                          rank=(float(item.cut),), target_override=item.target_hit,
                          axes=(("history", item.reason),))

    def card(self, assessment: Assessment) -> Card:
        item = assessment.detail
        fmt = lambda value: money(value, self.cfg.general.currency_symbol)
        facts = [f"Regular {fmt(item.regular)}; {item.cut}% off; {item.currency}"]
        if item.target_price is not None:
            facts.append(f"Your target: {fmt(item.target_price)} ({'met' if item.target_hit else 'not met'})")
        if item.expiry:
            days = (item.expiry - datetime.now(timezone.utc)).days
            if 0 <= days <= 21:
                facts.append(f"Sale ends in {days} day{'s' if days != 1 else ''}")
        bar, labels = (), ("", "")
        if item.steam_low is not None and item.regular > item.steam_low:
            position = max(2, min(100, round((item.price - item.steam_low)
                           / (item.regular - item.steam_low) * 100)))
            bar = ((position, "#2f6f4e"), (100 - position, "#e3e6ea"))
            labels = (f"low {fmt(item.steam_low)}", f"list {fmt(item.regular)}")
        colours = (("#0b6b3a", "#d7f2e3") if item.verdict >= Verdict.MATCHES_LOW else
                   ("#1c5d99", "#dbebfa") if item.verdict >= Verdict.BEST_THIS_YEAR else
                   ("#8a5a00", "#fdf0d5") if item.verdict == Verdict.DECENT else
                   ("#5c5f66", "#eceef1"))
        return Card(item.title, item.url, fmt(item.price),
                    item.verdict.label + (" · UNDER YOUR TARGET" if item.target_hit else ""),
                    item.headline, item.reason, tuple(facts), image=item.boxart,
                    bar=bar, bar_labels=labels, foreground=colours[0], background=colours[1])

    def report(self, buys: list[Assessment], others: list[Assessment], problems: list[str]) -> Report:
        cards = tuple(self.card(item) for item in buys)
        if len(cards) == 1:
            best = buys[0].detail
            subject = f"Steam: buy {best.title} - {cards[0].price} ({best.verdict.label.lower()})"
        elif cards:
            subject = f"Steam: {len(cards)} wishlist recommendations (incl. {cards[0].title} at {cards[0].price})"
        else:
            subject = "Steam wishlist: no new recommendations today"
        return Report(subject, f"{len(cards)} new recommendations" if cards else "No new recommendations",
                      f"{self.scored} discounted games assessed from {self.source.wishlist_size} wishlisted games.",
                      "Steam Deal Alerter · Price history from IsThereAnyDeal (isthereanydeal.com).",
                      cards, tuple(self.card(item) for item in others), tuple(problems))

    def persist(self) -> None:
        self.cache.save()

    def close(self) -> None:
        self.client.close()
