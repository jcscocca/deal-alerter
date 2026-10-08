"""Explain price evidence separately from budget targets and RAM suitability."""
from alerters.hardware.prebuilt import exact_desktop
from alerters.hardware.price_evidence import instant, positive


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
    stats["window_days"] = 90
    baseline = stats["median"] if stats["prior_days"] >= 3 else None
    stats["median"] = baseline
    stats["difference_pct"] = round(100 * (row["total"] / baseline - 1), 1) if baseline and current(row, now) else None
    label = "Collecting exact-build history"
    delta = stats["difference_pct"]
    if delta is not None:
        label = (f"{abs(delta):g}% {'below' if delta < 0 else 'above'} its historical median"
                 if delta else "At its historical median")
    elif stats["low"]:
        label = "Recorded prices available" if not baseline else "Historical median available"
    notes = ["Same listing, seller, condition and published configuration · last 90 days · before tax."]
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
    return {**stats, "label": label, "notes": notes}


def attach_values(rows, now):
    for row in rows:
        if row.get("lead") or not exact_desktop(row["title"]):
            continue
        row["prebuilt_value"] = {"history": history_view(row.get("price_history"), row, now)}
