"""Explain price evidence separately from budget targets and RAM suitability."""
import re
from statistics import median

from alerters.hardware.prebuilt import exact_desktop
from alerters.hardware.price_evidence import instant, positive
from alerters.hardware.prebuilt_specs import build_specs, normalized


def current(row, now):
    checked = instant(row.get("checked_at"))
    return (not row.get("lead") and row.get("available") is True
            and row.get("stock") == "in_stock" and positive(row.get("total"))
            and checked is not None and checked.timestamp() <= now
            and type(row.get("expires_at")) in (int, float) and now <= row["expires_at"]
            and not row.get("verification_reasons", row.get("reasons", [])))


def history_view(raw, row, now):
    raw = raw if isinstance(raw, dict) else {}
    stats = {k: raw.get(k) if positive(raw.get(k)) else None for k in ("median", "low", "high")}
    stats.update({k: raw.get(k) if type(raw.get(k)) is int and 0 <= raw[k] <= 20000 else 0
                  for k in ("observed_days", "prior_days", "legacy_prices")})
    stats.update({k: raw.get(k) if instant(raw.get(k)) else None for k in ("first_at", "last_at")})
    if not stats["low"] or not stats["high"] or stats["high"] < stats["low"]:
        stats["low"] = stats["high"] = None
    stats["window_days"] = 90
    baseline = stats["median"] if stats["prior_days"] >= 3 else None
    stats["median"] = baseline
    stats["difference_pct"] = round(100 * (row["total"] / baseline - 1), 1) if baseline and current(row, now) else None
    tracked = row.get("source") in ("walmart", "newegg", "hp", "cyberpowerpc", "skytech")
    label = "Collecting exact-build history" if tracked else "History not tracked for this source"
    delta = stats["difference_pct"]
    if delta is not None:
        label = (f"{abs(delta):g}% {'below' if delta < 0 else 'above'} its historical median"
                 if delta else "At its historical median")
    elif stats["low"]:
        label = "Recorded prices available" if not baseline else "Historical median available"
    notes = ["Same listing, seller, condition and published configuration · last 90 days · before tax."]
    if not tracked:
        notes.append("This source does not currently record exact-build daily price observations.")
    if stats["low"]:
        notes.append(f"Previously observed range: ${stats['low']:,.2f}–${stats['high']:,.2f}.")
    if baseline:
        notes.append(f"Median ${baseline:,.2f} across {stats['prior_days']} prior UTC days, using each day's last available total.")
    else:
        notes.append(f"{stats['prior_days']} prior daily samples; a historical median needs at least 3. Today's checks are excluded.")
    if stats["legacy_prices"]:
        notes.append(f"Includes {stats['legacy_prices']} older distinct-price records in the range only; they cannot establish a time average.")
    if not current(row, now):
        notes.append("Saved history only; check current price and stock before comparing this offer.")
    return {**stats, "label": label, "notes": notes, "tracked": tracked}


def seller_key(row):
    value = normalized(row.get("seller", ""))
    return {"walmartcom": "walmart", "neweggcom": "newegg", "skytechgaming": "skytech"}.get(value, value)


def sample_key(row, build):
    model = normalized(build["model"])
    # Generic model families are weak evidence. When an exact model is missing,
    # conservatively collapse a seller's offers with the same core specs.
    exact_model = model if len(model) >= 8 and re.search(r"[a-z]", model) and re.search(r"\d", model) else ""
    return (seller_key(row), exact_model, build["key"])


def peer_view(row, build, candidates, now):
    result = {"label": "Insufficient comparable offers", "count": 0, "sellers": 0,
              "median": None, "low": None, "high": None, "difference_pct": None,
              "confidence": "Insufficient data", "offers": [], "notes": []}
    notes = result["notes"]
    notes.append("Same GPU, exact CPU, RAM capacity/type, single SSD capacity and condition. Prices include known shipping and confirmed discounts, before tax.")
    if build["issues"]:
        notes += build["issues"]
        return result
    core = build["core"]
    result["configuration"] = f"RTX {core['gpu']} · {core['cpu']} · {core['ram_gb']}GB {core['ram_type']} · {core['ssd_gb']}GB SSD · {core['condition']}"
    if not current(row, now):
        result.update(label="Peer rating needs a current offer", confidence="Recheck required")
        notes.append("Current price and stock must be verified before assigning a peer rating.")
        return result
    selected = {}
    own = sample_key(row, build)
    for other, details in candidates:
        identity = sample_key(other, details)
        if (details["key"] != build["key"] or other["id"] == row["id"]
                or identity == own or not current(other, now)
                or seller_key(other) in ("", "notpublished", "unknown")):
            continue
        previous = selected.get(identity)
        if previous is None or other["total"] < previous["total"]:
            selected[identity] = other
    peers = sorted(selected.values(), key=lambda r: (r["total"], r["id"]))
    sellers = len({seller_key(r) for r in peers})
    result.update(count=len(peers), sellers=sellers,
                  offers=[{**{k: p[k] for k in ("id", "title", "seller", "retailer", "url", "total", "checked_at")},
                           "build_details": next(b["details"] for candidate,b in candidates if candidate is p)} for p in peers])
    notes.append("Current source sample only. This offer is excluded; repeated seller/model listings use their cheapest available quote. Missing model IDs collapse by seller and core specs.")
    if peers:
        result.update(low=peers[0]["total"], high=peers[-1]["total"])
    if len(peers) < 3 or sellers < 2:
        notes.append(f"Found {len(peers)} other comparable offers from {sellers} sellers; a rating needs at least 3 offers across 2 sellers.")
        return result
    typical = median(p["total"] for p in peers)
    delta = round(100 * (row["total"] / typical - 1), 1)
    label = "Below peer median" if delta <= -5 else "Above peer median" if delta >= 5 else "Near peer median"
    result.update(label=label, median=round(typical, 2), difference_pct=delta, confidence="Moderate · core specs matched")
    notes.append("Below/above means at least 5% from the sample median. This rates price against published core specs; component quality and performance are not scored.")
    return result


def attach_values(rows, now):
    candidates = [(r, build_specs(r["title"], r.get("build_specs", {}), r["condition"]))
                  for r in rows if not r.get("lead") and exact_desktop(r["title"])]
    for row, build in candidates:
        row["prebuilt_value"] = {"history": history_view(row.get("price_history"), row, now),
                                "peers": peer_view(row, build, candidates, now),
                                "build_details": build["details"], "build_issues": build["issues"],
                                "variable_parts": build["variable_parts"]}
