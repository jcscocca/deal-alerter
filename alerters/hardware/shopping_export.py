"""Public shopping snapshots from existing fetches; no credentials or extra requests."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json

from dealcore.state import atomic_write

MAX_ROWS = 2500


class ShoppingExport:
    def __init__(self, runtime):
        self.path = runtime / "shopping-sources.json"
        self.batches = {}
        self.activity_path = runtime / "shopping-activity.json"
        self.events = {}
        self.seen_path = runtime / "shopping-seen.json"
        self.seen = {}
        try:
            if self.seen_path.stat().st_size < 2_000_000:
                data = json.loads(self.seen_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.seen = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, ValueError, TypeError):
            pass
        try:
            if self.activity_path.stat().st_size < 4_000_000:
                data = json.loads(self.activity_path.read_text(encoding="utf-8"))
                self.events = {e["event_id"]: e for e in data["events"][-500:]}
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def record(self, key, batch, assessments, now, judgments=None):
        judgments = judgments or {}
        accepted = {(a.detail.source, a.detail.listing_id): a for a in assessments}
        rows = [{"type": "offer", "offer": asdict(offer), "judgment": judgments.get(offer.key)} for offer in batch.offers]
        for listing in batch.listings:
            community = listing.source.startswith(("slickdeals", "reddit"))
            assessment = accepted.get((listing.source, listing.listing_id))
            if listing.sold or not community and assessment is None:
                continue
            # Deliberately omit bodies, arbitrary extra fields and API response objects.
            shopping = listing.extra.get("shopping", {})
            detail = assessment.detail if assessment else None
            rows.append({"type": "listing", "id": listing.listing_id, "source": listing.source,
                         "title": listing.title[:1500], "url": listing.url,
                         "price": listing.price, "condition": listing.condition_hint,
                         "seller": listing.extra.get("seller", ""), "multi_variant": listing.multi_variant,
                         "seller_risk": listing.seller_risk, "seller_note": listing.seller_note,
                         "posted_at": listing.posted_at.isoformat(),
                         "quantity": getattr(assessment.detail, "quantity", 1) if assessment else 1,
                         "product_group": getattr(getattr(detail, "part", None), "name", ""),
                         "is_system": bool(getattr(detail, "is_system", False)),
                         "judgment": judgments.get(getattr(assessment, "key", "")),
                         "shopping": {name: shopping.get(name) for name in
                                      ("item_price", "shipping", "available")}})
        for row in rows:
            identity = row["offer"]["retailer"] + ":" + str(row["offer"]["sku"]) + json.dumps([row["offer"]["seller"], row["offer"]["condition"], row["offer"]["specs"]], sort_keys=True) if row["type"] == "offer" else row["source"] + ":" + row["id"]
            identity = hashlib.sha256(identity.encode()).hexdigest()[:24]
            row["first_seen"] = self.seen.setdefault(identity, now.isoformat())
        self.seen = dict(sorted(self.seen.items(), key=lambda e: e[1])[-10000:])
        # Latest batch replaces the source's prior result, including an empty success.
        self.batches[key] = {"observed_at": now.isoformat(), "rows": rows[:MAX_ROWS],
                             "truncated": len(rows) > MAX_ROWS}

    def record_activity(self, judgments):
        for judgment in judgments.values():
            events = [d for d in judgment["decisions"] if d["status"] in ("sent", "failed")]
            events += [{**d, "status": "sent", "receipt": True} for d in judgment["deliveries"]]
            for event in events:
                event = {**event, "at": datetime.fromisoformat(event["at"]).replace(microsecond=0).isoformat()}
                identity = hashlib.sha256(json.dumps([judgment["id"], event["channel"], event["status"], event["at"]]).encode()).hexdigest()[:24]
                row = {k: judgment[k] for k in ("id", "source", "title", "url", "verdict", "price")}
                self.events[identity] = {**row, **event, "event_id": identity}
        ordered = sorted(self.events.values(), key=lambda e: e["at"])[-500:]
        self.events = {e["event_id"]: e for e in ordered}
        atomic_write(self.activity_path, json.dumps({"version": 1, "events": ordered}, allow_nan=False))

    def write(self, jobs, heartbeat, *, dry_run=False):
        sources = []
        for key, job in jobs.items():
            if job["kind"].startswith("discover-"):
                continue
            sources.append({"source": job.get("source", job["kind"]),
                            "last_success": job.get("last_success", 0),
                            "failed": bool(job.get("error")), "interval": job["interval"],
                            **self.batches.get(key, {"observed_at": None, "rows": [], "truncated": False})})
        atomic_write(self.path, json.dumps({"version": 1, "capabilities": ["judgments", "watches"], "heartbeat": heartbeat,
                                           "dry_run": dry_run, "sources": sources}, allow_nan=False))
        if not dry_run:
            atomic_write(self.seen_path, json.dumps(self.seen))
