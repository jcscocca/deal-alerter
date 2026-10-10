"""Public projections of decisions already made by the existing alert engine."""
from __future__ import annotations

from dealcore.verdict import qualifies
from .shopping_controls import product_identity


def judgments(plugin, result, options, receipts, now):
    records = {}
    for item in result.assessments:
        card = plugin.card(item)
        source, identity = product_identity(item)
        detail = item.detail
        eligible = options.push_floor is not None and qualifies(item, options.push_floor)
        deliveries = [{"channel": name, "at": record.alerted_at.isoformat(), "price": record.price}
                      for name, record in receipts.records.get(receipts.normalise(item.key), {}).items()]
        records[item.key] = {"id": identity, "source": source, "title": detail.title[:1500], "url": card.url,
                             "verdict": item.verdict.name, "level": int(item.verdict), "badge": card.badge[:200],
                             "reason": card.reason[:1200], "headline": card.headline[:500],
                             "facts": [v[:1200] for v in card.facts[:12]], "warnings": [v[:1200] for v in card.warnings[:8]],
                             "eligible": eligible, "target_hit": bool(detail.target_hit),
                             "target": detail.target_price, "price": detail.total_price if item.price > 0 else None,
                             "checked_at": now.isoformat(), "deliveries": deliveries,
                             "decisions": [{k: d[k] for k in ("channel", "status", "at")}
                                           for d in result.decisions if d["key"] == item.key]}
        if item.key in getattr(plugin, "pc_details", {}):
            offer = plugin.pc_details[item.key][0]
            records[item.key]["price_history"] = plugin.pc_history.evidence(offer, now)
        if item.key in getattr(plugin, "sodimm_stock", {}):
            records[item.key]["stock_evidence"] = plugin.sodimm_stock[item.key]
    return records
