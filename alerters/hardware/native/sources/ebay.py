"""eBay Browse API -- the used market, where the 3090s and A6000s actually are.

Two things eBay gives you that nothing else does: structured prices (no
scraping "$1,599.99" out of a title) and a stated condition per listing. Both
matter a lot for the history log, since pooling used and new prices makes the
percentiles meaningless.

One thing it does *not* readily give you is sold prices. Browse returns active
listings, which are asking prices -- systematically above what things sell for.
Completed-sale data lives in the Marketplace Insights API, which requires
separate application and approval per developer account. `sold_search` here
will use it if your keyset has it and degrade quietly if not, so the tool works
either way and gets better if you get approved.

Free production keyset: https://developer.ebay.com/ -> create app -> App ID
(Client ID) and Cert ID (Client Secret).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import requests

from .base import Listing, SourceError

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
INSIGHTS_URL = (
    "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"
)
SCOPE = "https://api.ebay.com/oauth/api_scope"
TIMEOUT = 30
MARKETPLACE = "EBAY_US"

# eBay's condition IDs, mapped to the vocabulary match.py uses.
CONDITION_MAP = {
    "NEW": "new",
    "LIKE_NEW": "open_box",
    "NEW_OTHER": "open_box",
    "OPEN_BOX": "open_box",
    "CERTIFIED_REFURBISHED": "refurbished",
    "EXCELLENT_REFURBISHED": "refurbished",
    "VERY_GOOD_REFURBISHED": "refurbished",
    "GOOD_REFURBISHED": "refurbished",
    "SELLER_REFURBISHED": "refurbished",
    "USED_EXCELLENT": "used",
    "USED_VERY_GOOD": "used",
    "USED_GOOD": "used",
    "USED_ACCEPTABLE": "used",
    "PRE_OWNED_EXCELLENT": "used",
    "PRE_OWNED_FAIR": "used",
    "FOR_PARTS_OR_NOT_WORKING": "parts",
}

# Seller thresholds. eBay publishes these on every item summary, so they cost
# nothing extra -- the previous version fetched them and threw them away.
#
# None of these are proof of anything on their own. A brand-new account is how
# every honest seller starts, and plenty of legitimate hardware ships from Asia.
# Together they're the standard profile: a fresh account, imperfect feedback,
# and an origin that doesn't match the listing. So they combine into a tier that
# downgrades and blocks logging, rather than any one of them rejecting outright.
MIN_TRUSTED_FEEDBACK = 50
MIN_PLAUSIBLE_FEEDBACK = 10
MIN_TRUSTED_POSITIVE_PCT = 98.0
MIN_PLAUSIBLE_POSITIVE_PCT = 95.0
HOME_COUNTRY = "US"


def _seller_risk(item: dict) -> tuple[str, str]:
    """Grade the seller from what the Browse response already carries.

    Returns (risk, note). Missing seller data is *not* treated as risk: absent
    fields mean eBay didn't send them, which says nothing about the seller, and
    inventing suspicion from silence would downgrade everything.
    """
    seller = item.get("seller") or {}
    score = seller.get("feedbackScore")
    percentage = seller.get("feedbackPercentage")
    country = (item.get("itemLocation") or {}).get("country") or ""

    try:
        score = int(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    try:
        percentage = float(percentage) if percentage is not None else None
    except (TypeError, ValueError):
        percentage = None

    flags: list[str] = []
    serious = 0

    if score is not None and score < MIN_PLAUSIBLE_FEEDBACK:
        flags.append(f"the seller has {score} feedback")
        serious += 1
    elif score is not None and score < MIN_TRUSTED_FEEDBACK:
        flags.append(f"the seller has only {score} feedback")

    if percentage is not None and percentage < MIN_PLAUSIBLE_POSITIVE_PCT:
        flags.append(f"{percentage:.0f}% positive")
        serious += 1
    elif percentage is not None and percentage < MIN_TRUSTED_POSITIVE_PCT:
        flags.append(f"{percentage:.0f}% positive")

    if country and country != HOME_COUNTRY:
        flags.append(f"ships from {country}")
        if flags[:-1]:
            serious += 1

    if not flags:
        return "low", ""
    note = ", ".join(flags)
    return ("high" if serious else "moderate"), note


class EbaySource:
    def __init__(
        self,
        queries: tuple[str, ...],
        *,
        client_id: str,
        client_secret: str,
        limit_per_query: int = 50,
        include_sold: bool = True,
        price_floors: dict[str, float] | None = None,
    ) -> None:
        self.name = "ebay"
        self.queries = queries
        # query -> lowest plausible price. Without it, sorting cheapest-first
        # spends the whole result window on accessories: a "RTX 3090" search
        # returns thousands of matches whose cheapest 50 are stickers and
        # brackets, and not one actual card.
        self.price_floors = price_floors or {}
        self.client_id = client_id
        self.client_secret = client_secret
        self.limit_per_query = limit_per_query
        self.include_sold = include_sold
        self.session = requests.Session()
        self._token: str | None = None
        # Set once we learn the keyset lacks Marketplace Insights, so we stop
        # asking on every subsequent query.
        self._insights_denied = False

    def _authenticate(self) -> str:
        if self._token:
            return self._token
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        try:
            resp = self.session.post(
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": SCOPE},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"eBay auth request failed: {exc}") from exc

        if resp.status_code != 200:
            raise SourceError(
                f"eBay rejected the credentials ({resp.status_code}). Confirm "
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET come from a *production* "
                "keyset, not sandbox."
            )
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._authenticate()}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
            "Content-Type": "application/json",
        }

    def fetch(self) -> list[Listing]:
        listings: list[Listing] = []
        failures: list[str] = []
        for query in self.queries:
            try:
                listings.extend(self._search_active(query))
            except SourceError as exc:
                failures.append(f"{query!r}: {exc}")
            if self.include_sold and not self._insights_denied:
                try:
                    listings.extend(self._search_sold(query))
                except SourceError:
                    # Already recorded via _insights_denied; not worth surfacing
                    # per query since the whole feature is optional.
                    pass
        if failures and not listings:
            raise SourceError("; ".join(failures))
        return listings

    def _search_active(self, query: str) -> list[Listing]:
        # Buy-It-Now only. Auction prices mid-flight are not prices; a 3090
        # sitting at $200 with two days left tells you nothing.
        filters = ["buyingOptions:{FIXED_PRICE}"]
        floor = self.price_floors.get(query)
        if floor:
            # eBay requires priceCurrency whenever a price filter is present.
            filters.append(f"price:[{floor:.0f}..],priceCurrency:USD")
        try:
            resp = self.session.get(
                BROWSE_URL,
                headers=self._headers(),
                params={
                    "q": query,
                    "limit": self.limit_per_query,
                    # Deliberately unsorted -- eBay's Best Match. Sorting by
                    # price ascending seems obviously right for deal-hunting and
                    # is a trap: "RTX 3090" matches thousands of items and the
                    # cheap end is a wall of stickers, fans, water blocks and
                    # NVLink bridges. Measured live on the same query: price
                    # sort returned 50 items spanning $189-$290 of which none
                    # were a card, while Best Match returned $200-$2,000 with
                    # 45 of 50 resolving to a real part. You give up seeing the
                    # single cheapest listing and get to see cards at all.
                    "filter": ",".join(filters),
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}")

        now = datetime.now(timezone.utc)
        out: list[Listing] = []
        for item in resp.json().get("itemSummaries") or []:
            price = _price_of(item)
            if price is None:
                continue
            risk, note = _seller_risk(item)
            variant = _variant_of_many(item.get("itemId", ""))
            out.append(
                Listing(
                    listing_id=item.get("itemId", ""),
                    source="ebay",
                    title=item.get("title", ""),
                    url=item.get("itemWebUrl", ""),
                    # Browse doesn't return a listing date on summaries. Active
                    # listings are current by definition, so treat them as now
                    # rather than dropping them on the age filter.
                    posted_at=now,
                    price=price,
                    condition_hint=CONDITION_MAP.get(
                        (item.get("condition") or "").upper().replace(" ", "_"), ""
                    ),
                    seller_risk=risk,
                    seller_note=note,
                    # Logged, as of 2026-08-08. These were excluded when the
                    # query sorted cheapest-first and returned 50 stickers per
                    # search -- a distribution of the cheap tail, which would
                    # have made genuinely good prices look ordinary. Under Best
                    # Match with a price floor that reasoning no longer holds,
                    # and holding out for a *neutral* sample was a standard the
                    # rest of the log never met: Reddit is "what got posted
                    # today" and Slickdeals is an aggregator selected for low
                    # prices, both logged without complaint. Best Match skews
                    # toward competitively-priced listings, which is nearer the
                    # market than either.
                    #
                    # These are asking prices. That is what `sold` is for:
                    # price_stats() switches a part to sold-only the moment it
                    # has enough confirmed sales, so Insights data supersedes
                    # this automatically rather than averaging with it.
                    #
                    # Except for variation listings, which are never an
                    # observation of anything. Which option Browse returns is
                    # its choice rather than the market's, and the same listing
                    # comes back under different options on different queries:
                    # the log picked up one ASUS workstation three times over,
                    # at $3,999, $4,599 and $4,999, as though three machines
                    # had been for sale.
                    loggable=not variant,
                    multi_variant=variant,
                    extra={
                        "seller": (item.get("seller") or {}).get("username", ""),
                        "country": (item.get("itemLocation") or {}).get("country", ""),
                    },
                )
            )
        return out

    def _search_sold(self, query: str) -> list[Listing]:
        """Completed sales, when the keyset is approved for Marketplace Insights.

        These are the observations actually worth having: what someone paid, not
        what someone hoped for. Seeded into history with sold=True.

        Unlike the active search these *are* logged, because they're filtered by
        sale date rather than sorted by price -- a fair sample of what the market
        actually cleared, not its cheap tail.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        try:
            resp = self.session.get(
                INSIGHTS_URL,
                headers=self._headers(),
                params={
                    "q": query,
                    "limit": self.limit_per_query,
                    "filter": f"lastSoldDate:[{since}..]",
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            self._insights_denied = True
            raise SourceError(
                "Marketplace Insights not enabled for this keyset (sold-price "
                "history will be skipped). Apply at developer.ebay.com if you "
                "want it -- everything else works without it."
            )
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}")

        out: list[Listing] = []
        for item in resp.json().get("itemSales") or []:
            price = _price_of(item)
            if price is None:
                continue
            sold_at = _parse_iso(item.get("lastSoldDate")) or datetime.now(timezone.utc)
            # Insights ids carry the same variation segment Browse ids do, and
            # the same title-belongs-to-the-group problem with it. This path
            # needs the guard *more* than the active one, not less: a sold row
            # is the observation the whole log defers to, since price_stats()
            # switches a part to sold-only the moment it has enough confirmed
            # sales. A variation-level sale would arrive with that authority and
            # supersede every honest asking price behind it. Checked before the
            # prefix goes on, because `sold-v1|...` is not an item id any more.
            variant = _variant_of_many(item.get("itemId", ""))
            out.append(
                Listing(
                    listing_id=f"sold-{item.get('itemId', '')}",
                    source="ebay-sold",
                    title=item.get("title", ""),
                    url=item.get("itemWebUrl", ""),
                    posted_at=sold_at,
                    price=price,
                    condition_hint=CONDITION_MAP.get(
                        (item.get("condition") or "").upper().replace(" ", "_"), ""
                    ),
                    sold=True,
                    loggable=not variant,
                    multi_variant=variant,
                )
            )
        return out


def _variant_of_many(item_id: str) -> bool:
    """Is this one option inside a multi-variation listing?

    Browse item ids are `v1|<listing>|<variation>`, and the variation segment
    is 0 on an ordinary listing. When it isn't, one dropdown option has been
    handed back under the group's title, and nothing else in the response says
    which option that title describes. Observed live on 2026-08-13: a "Dell
    NVIDIA GeForce RTX 3060 3070 3080 3090 ... 24GB" listing returned
    `v1|318721947819|616991316905` at $593.40, which is its 3060 Ti 8GB. The
    3090 option in the same listing is $2,187.55.
    """
    segments = item_id.split("|")
    return len(segments) >= 3 and segments[2] not in ("", "0")


def _price_of(item: dict) -> float | None:
    raw = item.get("price") or item.get("lastSoldPrice") or {}
    try:
        return float(raw["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
