"""Wishlist/current-price intake and ITAD transport; no price-history policy."""
from __future__ import annotations

import copy
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from dealcore.state import atomic_write
from dealcore.types import FetchResult, Listing, SourceError

BASE = "https://api.isthereanydeal.com"
STEAM_SHOP_ID, BATCH_SIZE, TIMEOUT = 61, 200, 30


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = "USD"


@dataclass(frozen=True)
class Deal:
    price: Money
    regular: Money
    cut: int
    url: str = ""
    expiry: datetime | None = None
    store_low: Money | None = None


@dataclass(frozen=True)
class GamePrices:
    itad_id: str
    deal: Deal | None
    low_all: Money | None = None
    low_y1: Money | None = None


@dataclass(frozen=True)
class StoreLow:
    price: Money
    at: datetime | None
    cut: int = 0


@dataclass(frozen=True)
class HistoryPoint:
    at: datetime
    price: float
    cut: int


def timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_money(raw: dict | None) -> Money | None:
    if raw is None:
        return None
    amount = float(raw["amount"])
    if not isfinite(amount) or amount < 0:
        raise SourceError("ITAD supplied an invalid price")
    return Money(amount, str(raw["currency"]))


def required_money(raw: dict) -> Money:
    result = parse_money(raw)
    if result is None:
        raise SourceError("ITAD omitted a required price")
    return result


class ItadClient:
    """The same API client may serve two capabilities without merging them."""
    def __init__(self, key: str, country: str, *, replay: dict | None = None,
                 session: requests.Session | None = None) -> None:
        self.country, self.replay = country, replay
        self.session = session or requests.Session()
        self.session.headers.update({"ITAD-API-Key": key, "User-Agent": "deal-alerter/1"})
        self.request_count = 0

    def json(self, method: str, path: str, *, params: dict | None = None, body=None):
        params = params or {}
        if self.replay is not None:
            value = self.replay["responses"][path]
            return copy.deepcopy(value[params["id"]] if "id" in params else value)
        for attempt in range(3):
            self.request_count += 1
            try:
                response = self.session.request(method, BASE + path, params=params,
                                                json=body, timeout=TIMEOUT)
            except requests.RequestException as exc:
                raise SourceError(f"ITAD {path}: {type(exc).__name__}") from None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                try:
                    delay = float(response.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    delay = 2 ** attempt
                # Do not hammer an explicitly longer rate-limit window.
                if delay > 300:
                    raise SourceError("ITAD rate limited; retry on a later run")
                time.sleep(max(delay, 0))
                continue
            if response.status_code >= 400:
                raise SourceError(f"ITAD {path}: HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError:
                raise SourceError(f"ITAD {path}: invalid JSON") from None
        raise SourceError("ITAD retry budget exhausted")

    def map_steam_appids(self, appids: list[int]) -> dict[int, str]:
        mapped = {}
        for start in range(0, len(appids), BATCH_SIZE):
            batch = appids[start:start + BATCH_SIZE]
            raw = self.json("POST", f"/lookup/id/shop/{STEAM_SHOP_ID}/v1",
                            body=[f"app/{appid}" for appid in batch])
            for appid in batch:
                if value := raw.get(f"app/{appid}"):
                    mapped[appid] = str(value)
        return mapped

    def steam_prices(self, ids: list[str], *, deals_only: bool = True) -> dict[str, GamePrices]:
        result = {}
        for start in range(0, len(ids), BATCH_SIZE):
            batch = ids[start:start + BATCH_SIZE]
            rows = self.json("POST", "/games/prices/v3", body=batch,
                             params={"country": self.country, "shops": str(STEAM_SHOP_ID),
                                     "deals": str(deals_only).lower()})
            for row in rows:
                if row["id"] not in batch:
                    continue
                deals = []
                for raw in row.get("deals", []):
                    # A Steam key sold elsewhere is not a Steam-store sale.
                    if raw["shop"]["id"] != STEAM_SHOP_ID:
                        continue
                    price, regular = required_money(raw["price"]), required_money(raw["regular"])
                    if price.currency != regular.currency:
                        raise SourceError("ITAD mixed currencies within a deal")
                    deals.append(Deal(price, regular, int(raw["cut"]), raw.get("url") or "",
                                      timestamp(raw.get("expiry")), parse_money(raw.get("storeLow"))))
                low = row.get("historyLow") or {}
                result[row["id"]] = GamePrices(row["id"], min(deals, key=lambda d: d.price.amount)
                                               if deals else None, parse_money(low.get("all")),
                                               parse_money(low.get("y1")))
        return result

    def steam_store_lows(self, ids: list[str]) -> dict[str, StoreLow]:
        result = {}
        for start in range(0, len(ids), BATCH_SIZE):
            batch = ids[start:start + BATCH_SIZE]
            rows = self.json("POST", "/games/storelow/v2", body=batch,
                             params={"country": self.country, "shops": str(STEAM_SHOP_ID)})
            for row in rows:
                if row["id"] not in batch:
                    continue
                for raw in row["lows"]:
                    if raw["shop"]["id"] == STEAM_SHOP_ID:
                        result[row["id"]] = StoreLow(required_money(raw["price"]),
                                                     timestamp(raw.get("timestamp")), int(raw["cut"]))
        return result

    def game_info(self, game_id: str) -> dict:
        return self.json("GET", "/games/info/v2", params={"id": game_id})

    def steam_history(self, game_id: str, *, years: int, currency: str) -> list[HistoryPoint]:
        since = datetime.now(timezone.utc) - timedelta(days=365.25 * years)
        rows = self.json("GET", "/games/history/v2", params={"id": game_id,
                         "country": self.country, "shops": str(STEAM_SHOP_ID),
                         "since": since.isoformat(timespec="seconds")})
        result = []
        for row in rows:
            if row["shop"]["id"] != STEAM_SHOP_ID or row.get("deal") is None:
                continue
            price = required_money(row["deal"]["price"])
            if price.currency != currency:
                raise SourceError("History currency differs from today's price")
            at = timestamp(row["timestamp"])
            if at is None:
                raise SourceError("History point has no timestamp")
            result.append(HistoryPoint(at, price.amount, int(row["deal"]["cut"])))
        # The API's example is newest-first; episode counting needs oldest-first.
        return sorted(result, key=lambda point: point.at)

    def close(self) -> None:
        self.session.close()


class WishlistError(SourceError):
    """An unreadable wishlist is not evidence that every sale ended."""


def resolve_steam_id(value: str, session: requests.Session) -> str:
    value = value.strip()
    if "://" in value:
        parsed = urlparse(value)
        pieces = parsed.path.strip("/").split("/")
        if parsed.hostname != "steamcommunity.com" or len(pieces) != 2 or pieces[0] not in ("id", "profiles"):
            raise WishlistError("Use a SteamID64, vanity name or Steam community profile URL")
        value = pieces[1]
    if re.fullmatch(r"[0-9]{17}", value):
        return value
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise WishlistError("Invalid Steam vanity name")
    try:
        response = session.get(f"https://steamcommunity.com/id/{quote(value)}/",
                               params={"xml": 1}, timeout=TIMEOUT)
        response.raise_for_status()
        steam_id = ET.fromstring(response.text).findtext("steamID64") or ""
    except (requests.RequestException, ET.ParseError):
        raise WishlistError("Could not resolve Steam vanity name") from None
    if not re.fullmatch(r"[0-9]{17}", steam_id):
        raise WishlistError("Steam profile has no SteamID64")
    return steam_id


def fetch_wishlist_appids(steam_id: str, session: requests.Session) -> list[int]:
    try:
        response = session.get("https://api.steampowered.com/IWishlistService/GetWishlist/v1/",
                               params={"steamid": steam_id}, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()["response"]
        rows = payload["items"]
        return list(dict.fromkeys(int(row["appid"]) for row in
                    sorted(rows, key=lambda row: row.get("date_added", 0), reverse=True)))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        # A missing items field is ambiguous (private/unavailable/empty). Do not
        # turn it into an authoritative empty result and erase alert receipts.
        raise WishlistError("Wishlist unavailable or ambiguous; check public Game details") from None


class TitleCache:
    """Game titles and box art change rarely; look them up once and keep them."""
    def __init__(self, path: Path) -> None:
        self.path, self.dirty = path, False
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def get(self, game_id: str) -> dict | None:
        return self.data.get(game_id)

    def put(self, game_id: str, title: str, boxart: str | None) -> None:
        self.data[game_id] = {"title": title, "boxart": boxart}
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            atomic_write(self.path, json.dumps(self.data, indent=1, sort_keys=True) + "\n")
            self.dirty = False


class SteamSource:
    name = "steam"

    def __init__(self, client: ItadClient, steam_id: str, min_cut: int) -> None:
        self.client, self.steam_id, self.min_cut = client, steam_id, min_cut
        self.wishlist_size = 0
        self.live_ids: list[str] = []

    def fetch(self) -> FetchResult:
        with requests.Session() as session:
            appids = (self.client.replay["appids"] if self.client.replay is not None else
                      fetch_wishlist_appids(resolve_steam_id(self.steam_id, session), session))
        self.wishlist_size = len(appids)
        mapping = self.client.map_steam_appids(appids)
        prices = self.client.steam_prices(list(dict.fromkeys(mapping.values())))
        result = []
        self.live_ids = []
        for appid, game_id in mapping.items():
            game = prices.get(game_id)
            if game is None or game.deal is None or game.deal.cut < self.min_cut:
                continue
            self.live_ids.append(game_id)
            result.append(Listing(str(appid), self.name, f"App {appid}",
                          game.deal.url or f"https://store.steampowered.com/app/{appid}/",
                          datetime.now(timezone.utc), game.deal.price.amount,
                          loggable=False, extra={"prices": game}))
        # An unmapped title might be an API coverage gap, not a vanished sale.
        complete = frozenset({self.name}) if len(mapping) == len(appids) else frozenset()
        return FetchResult(result, complete)
