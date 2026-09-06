"""Delegated evidence. No observations are invented from today's wishlist."""
from __future__ import annotations

from dataclasses import dataclass

from dealcore.types import SourceError
from .sources import GamePrices, HistoryPoint, ItadClient, SteamSource, StoreLow


@dataclass(frozen=True)
class Candidate:
    appid: int
    title: str
    boxart: str | None
    prices: GamePrices
    target: float | None


@dataclass(frozen=True)
class Evidence:
    store_low: StoreLow | None
    points: list[HistoryPoint]


class SteamHistory:
    def __init__(self, client: ItadClient, source: SteamSource, years: int) -> None:
        self.client, self.source, self.years = client, source, years
        self.lows: dict[str, StoreLow] | None = None
        self.failure: SourceError | None = None

    def read(self, candidate: Candidate) -> Evidence:
        if self.failure is not None:
            raise self.failure
        if self.lows is None:
            try:
                self.lows = self.client.steam_store_lows(self.source.live_ids)
            except SourceError as exc:
                # One failed batch must not be retried once per wishlisted game.
                self.failure = exc
                raise
        deal = candidate.prices.deal
        if deal is None:
            raise ValueError("History requested for a game with no current deal")
        low = self.lows.get(candidate.prices.itad_id)
        monies = [low.price if low else None, deal.store_low,
                  candidate.prices.low_all, candidate.prices.low_y1]
        if any(value is not None and value.currency != deal.price.currency for value in monies):
            raise SourceError("Benchmark currency differs from today's price")
        # A successful empty history is weak evidence. A failed request is not
        # empty history: propagate it, withhold this assessment, preserve state.
        points = self.client.steam_history(candidate.prices.itad_id, years=self.years,
                                           currency=deal.price.currency)
        return Evidence(low, points)
