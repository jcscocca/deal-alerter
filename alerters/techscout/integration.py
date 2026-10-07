"""Read public monitor decisions and manage its narrow, non-secret UI settings."""
from __future__ import annotations

import hashlib
import json
import math
import re

from dealcore.state import atomic_write
from alerters.hardware.shopping_controls import defaults, read_controls, validate

STATUSES = {"sent": "Sent", "failed": "Send failed", "unchanged": "Already notified; no qualifying change",
            "ineligible": "Below notification rules or evidence requirements", "watch-filtered": "Outside enabled watches / paused",
            "dry-run": "Preview only", "pending": "Outcome unavailable"}
CHANNELS = {"email", "ntfy", "discord", "desktop"}


def read_public(path, limit=12_000_000):
    try:
        if path.stat().st_size > limit:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def text(value, limit=1200):
    return value[:limit] if isinstance(value, str) else ""


def price(value):
    # Announcement receipts use zero as an unknown-price sentinel. Retained
    # events must not present that bookkeeping value as a free product.
    return value if type(value) in (int, float) and math.isfinite(value) and 0 < value < 1_000_000 else None


def judgment(raw):
    if not isinstance(raw, dict) or raw.get("verdict") not in ("PASS", "FAIR", "GOOD", "STRONG", "EXCEPTIONAL", "GRAIL"):
        return None
    return {"verdict": raw["verdict"], "level": ("PASS", "FAIR", "GOOD", "STRONG", "EXCEPTIONAL", "GRAIL").index(raw["verdict"]),
            "badge": text(raw.get("badge"), 200), "reason": text(raw.get("reason")), "headline": text(raw.get("headline"), 500),
            "eligible": raw.get("eligible") is True, "target_hit": raw.get("target_hit") is True,
            "target": price(raw.get("target")), "checked_at": text(raw.get("checked_at"), 50),
            "facts": [text(v) for v in raw.get("facts", [])[:12] if isinstance(v, str)] if isinstance(raw.get("facts"), list) else [],
            "warnings": [text(v) for v in raw.get("warnings", [])[:8] if isinstance(v, str)] if isinstance(raw.get("warnings"), list) else [],
            "decisions": [d for d in (decision(v) for v in raw.get("decisions", [])[:8]) if d] if isinstance(raw.get("decisions"), list) else []}


def decision(raw):
    from .monitor_bridge import stamp
    if not isinstance(raw, dict) or not isinstance(raw.get("status"), str) or not isinstance(raw.get("channel"), str) or raw["status"] not in STATUSES or raw["channel"] not in CHANNELS or stamp(raw.get("at")) is None:
        return None
    return {"status": raw["status"], "label": STATUSES[raw["status"]], "channel": raw["channel"], "at": raw["at"]}


def activity(runtime):
    from .monitor_bridge import safe_url, HOSTS, stamp
    if runtime is None:
        return []
    data = read_public(runtime / "shopping-activity.json", 4_000_000)
    rows = []
    for raw in data.get("events", [])[-500:] if isinstance(data.get("events"), list) else []:
        item = decision(raw)
        if not item or not isinstance(raw.get("id"), str) or not re.fullmatch(r"[a-z-]+:[a-f0-9]{24}", raw["id"]):
            continue
        url = next((url for source in HOSTS if (url := safe_url(raw.get("url"), source))), None)
        if url:
            rows.append({**item, "id": raw["id"], "title": text(raw.get("title"), 1500), "url": url,
                         "price": price(raw.get("price")), "source": text(raw.get("source"), 40)})
    return sorted(rows, key=lambda r: stamp(r["at"]), reverse=True)


def revision(settings):
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


class Workspace:
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def path(self):
        return self.runtime / "ui" / "watches.json"

    def state(self):
        data = read_public(self.runtime / "shopping-sources.json") if self.runtime else {}
        settings, error = read_controls(self.path) if self.runtime else (defaults(), "Monitor is not connected")
        return {"settings": settings, "revision": revision(settings), "error": error,
                "supported": isinstance(data.get("capabilities"), list) and "watches" in data["capabilities"], "activity": activity(self.runtime)}

    def update(self, body):
        if not isinstance(body, dict) or set(body) != {"revision", "settings"}:
            return 400, {"error": "Invalid watch request"}
        try:
            settings = validate(body["settings"])
        except (ValueError, TypeError, KeyError) as exc:
            return 400, {"error": text(str(exc), 120)}
        current = self.state()
        if not current["supported"]:
            return 409, {"error": "Update the installed monitor before changing notification watches"}
        if body["revision"] != current["revision"]:
            return 409, {"error": "Settings changed in another window. Reload Watching and try again."}
        if not self.path.parent.is_dir() or self.path.parent.is_symlink() or self.path.is_symlink():
            return 503, {"error": "The dashboard watch folder needs local setup"}
        try:
            atomic_write(self.path, json.dumps(settings, allow_nan=False))
        except OSError:
            return 503, {"error": "The dashboard cannot save watches. Run the local integration setup."}
        return 200, {"settings": settings, "revision": revision(settings)}
