"""Bounded, observed complete-PC prices; daily samples are not sale transactions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import median

from dealcore.state import atomic_write

WINDOW_DAYS = 90


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1_000_000


def instant(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def configuration_key(source, sku, seller, condition, title, specs, region=""):
    # Deliberately conservative: changed configuration, seller or delivery region
    # starts new evidence, even if a retailer reuses its product ID.
    values = [source, str(sku), seller, condition, title, specs, region]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def offer_key(offer):
    return configuration_key(offer.retailer, offer.sku, offer.seller, offer.condition,
                             offer.title, offer.specs)


class PriceEvidence:
    """One last observed total per configuration/UTC day, plus that day's range."""
    def __init__(self, path):
        self.path, self.rows = path, []
        try:
            if path.stat().st_size <= 8_000_000:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("version") == 1 and isinstance(data.get("rows"), list):
                    self.rows = [r for r in data["rows"] if self.valid(r)][-20000:]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    @staticmethod
    def valid(row):
        return (isinstance(row, dict) and isinstance(row.get("key"), str)
                and instant(row.get("at")) is not None
                and all(positive(row.get(k)) for k in ("total", "low", "high"))
                and row["low"] <= row["total"] <= row["high"])

    def record(self, key, total, at):
        when = instant(at)
        if not when or not positive(total):
            return
        cutoff = when - timedelta(days=WINDOW_DAYS)
        self.rows = [r for r in self.rows if instant(r["at"]) >= cutoff]
        previous = next((r for r in self.rows if r["key"] == key and instant(r["at"]).date() == when.date()), None)
        if previous:
            # A saved/older lookup must not replace a more recent observation.
            if when <= instant(previous["at"]):
                return
            previous.update(total=total, at=when.isoformat(), low=min(previous["low"], total), high=max(previous["high"], total))
        else:
            self.rows.append({"key": key, "at": when.isoformat(), "total": total, "low": total, "high": total})
        self.rows = sorted(self.rows, key=lambda r: r["at"])[-20000:]

    def summary(self, key, at, legacy=()):
        when = instant(at)
        result = {"window_days": WINDOW_DAYS, "observed_days": 0, "prior_days": 0,
                  "legacy_prices": 0, "median": None, "low": None, "high": None,
                  "first_at": None, "last_at": None}
        if not when:
            return result
        cutoff = when - timedelta(days=WINDOW_DAYS)
        rows = [r for r in self.rows if r["key"] == key and cutoff <= instant(r["at"]) <= when]
        result["observed_days"] = len(rows)
        # Exclude today so repeated polling or a price changing within this check
        # cannot vote multiple times or move its own historical baseline.
        prior = [r for r in rows if instant(r["at"]).date() < when.date()]
        old = [r for r in legacy if isinstance(r, dict) and positive(r.get("total"))
               and instant(r.get("seen_at")) is not None
               and cutoff <= instant(r["seen_at"]) <= when
               and instant(r["seen_at"]).date() < when.date()]
        result.update(prior_days=len(prior), legacy_prices=len(old))
        # Legacy history only retained distinct prices. Its range is useful,
        # but averaging those records would over-weight price changes.
        if len(prior) >= 3:
            result["median"] = round(median(r["total"] for r in prior), 2)
        if prior or old:
            result["low"] = min([r["low"] for r in prior] + [r["total"] for r in old])
            result["high"] = max([r["high"] for r in prior] + [r["total"] for r in old])
            dates = [r["at"] for r in prior] + [r["seen_at"] for r in old]
            result.update(first_at=min(dates, key=instant), last_at=max(dates, key=instant))
        return result

    def save(self):
        atomic_write(self.path, json.dumps({"version": 1, "rows": self.rows}, allow_nan=False))
