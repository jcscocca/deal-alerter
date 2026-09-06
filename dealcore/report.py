"""Email-safe tables and escaped text; shopping language comes from plugins.

Mail clients need tables and inline styles, not flexbox, SVG or a stylesheet
whose behavior depends on the recipient. Plugins supply geometry, not HTML.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlparse

from .types import Card, Report


def safe_url(url: str | None) -> str:
    # Sources supply attacker-controlled links. In particular, a desktop click
    # must not hand file:// or a registered application scheme to macOS open.
    try:
        parsed = urlparse(url or "")
        return url if parsed.scheme in ("http", "https") and parsed.netloc else ""
    except ValueError:
        return ""


def card_html(card: Card) -> str:
    url = escape(safe_url(card.url), quote=True)
    image = safe_url(card.image)
    art = f'<img src="{escape(image, quote=True)}" width="92" alt="">' if image else ""
    facts = "".join(f"<div>{escape(text)}</div>" for text in card.facts)
    flags = "".join(f'<div style="color:#b3261e;">{escape(text)}</div>' for text in card.warnings)
    bar = ""
    if card.bar:
        if any(n < 0 for n, _ in card.bar) or sum(n for n, _ in card.bar) != 100:
            raise ValueError("A presentation bar must partition 100 percent")
        cells = "".join(f'<td width="{n}%" style="background:{escape(colour)};height:7px;">'
                        "</td>" for n, colour in card.bar if n)
        bar = (f'<table role="presentation" width="100%"><tr>{cells}</tr></table>'
               f'<div>{escape(card.bar_labels[0])} / {escape(card.bar_labels[1])}</div>')
    return (f'<table role="presentation" width="100%" cellpadding="14" '
            f'style="background:#ffffff;border:1px solid #dfe3e8;margin-bottom:14px;">'
            f'<tr><td>{art}<span style="color:{escape(card.foreground)};'
            f'background:{escape(card.background)};">{escape(card.badge)}</span>'
            f'<h3><a href="{url}">{escape(card.title)}</a></h3>'
            f'<strong>{escape(card.price)}</strong><p>{escape(card.headline)}</p>'
            f'<p>{escape(card.reason)}</p>{facts}{flags}{bar}</td></tr></table>')


def render_html(report: Report) -> str:
    problems = "".join(f"<p>{escape(p)}</p>" for p in report.problems)
    others = ""
    if report.others:
        others = "<h2>Also seen</h2>" + "".join(card_html(c) for c in report.others)
    return ('<!doctype html><html><body style="background:#f4f6f8;">'
            '<table role="presentation" width="100%"><tr><td align="center">'
            '<table role="presentation" width="640" style="max-width:640px;width:100%;'
            'font:14px Arial,sans-serif;"><tr><td>'
            f'<h1>{escape(report.heading)}</h1><p>{escape(report.summary)}</p>{problems}'
            + "".join(card_html(c) for c in report.buys) + others
            + f'<p>{escape(report.footer)}</p></td></tr></table></td></tr></table></body></html>')


def render_text(report: Report) -> str:
    lines = [report.heading, report.summary, *report.problems, ""]
    for title, cards in (("", report.buys), ("Also seen", report.others)):
        if cards and title:
            lines.append(title)
        for card in cards:
            lines.extend([f"[{card.badge}] {card.title} — {card.price}", card.headline,
                          card.reason, *card.facts, *card.warnings, safe_url(card.url), ""])
    return "\n".join([*lines, report.footer])
