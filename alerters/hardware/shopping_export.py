"""Public shopping snapshots from existing fetches; no credentials or extra requests."""
from __future__ import annotations

from dataclasses import asdict
import json

from dealcore.state import atomic_write

MAX_ROWS = 2500


class ShoppingExport:
    def __init__(self, runtime):
        self.path = runtime / "shopping-sources.json"
        self.batches = {}

    def record(self, key, batch, assessments, now):
        accepted = {(a.detail.source, a.detail.listing_id): a for a in assessments}
        rows = [{"type": "offer", "offer": asdict(offer)} for offer in batch.offers]
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
                         "shopping": {name: shopping.get(name) for name in
                                      ("item_price", "shipping", "available")}})
        # Latest batch replaces the source's prior result, including an empty success.
        self.batches[key] = {"observed_at": now.isoformat(), "rows": rows[:MAX_ROWS],
                             "truncated": len(rows) > MAX_ROWS}

    def write(self, jobs, heartbeat, *, dry_run=False):
        sources = []
        for key, job in jobs.items():
            if job["kind"].startswith("discover-"):
                continue
            sources.append({"source": job.get("source", job["kind"]),
                            "last_success": job.get("last_success", 0),
                            "failed": bool(job.get("error")), "interval": job["interval"],
                            **self.batches.get(key, {"observed_at": None, "rows": [], "truncated": False})})
        atomic_write(self.path, json.dumps({"version": 1, "heartbeat": heartbeat,
                                           "dry_run": dry_run, "sources": sources}, allow_nan=False))
