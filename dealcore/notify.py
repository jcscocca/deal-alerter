"""Transport only. Priorities, titles and purchase advice belong to the plugin."""
from __future__ import annotations

import os
import shutil
import smtplib
import ssl
import subprocess
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Callable

import requests

from .config import require_env
from .report import render_html, render_text, safe_url
from .types import Report


class NotificationError(RuntimeError):
    """A delivery did not earn a receipt."""


@dataclass(frozen=True)
class Channel:
    name: str
    kind: str  # email or push; state is independent for each actual transport
    send: Callable[[Report], None]


def send_email(report: Report) -> None:
    message = EmailMessage()
    message["Subject"] = " ".join(report.subject.split())
    message["From"] = os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"]
    message["To"] = os.environ["MAIL_TO"]
    message.set_content(render_text(report))
    message.add_alternative(render_html(report), subtype="html")
    host, port = os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", 587))
    context = ssl.create_default_context()
    server = (smtplib.SMTP_SSL(host, port, timeout=60, context=context)
              if port == 465 else smtplib.SMTP(host, port, timeout=60))
    with server:
        if port != 465:
            server.starttls(context=context)
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        if server.send_message(message):
            # Retrying may duplicate the accepted recipients, but pretending the
            # whole digest arrived would permanently lose the refused ones.
            raise NotificationError("SMTP refused one or more recipients")


def post(url: str, **kwargs) -> None:
    try:
        response = requests.post(url, timeout=20, **kwargs)
        response.raise_for_status()
    except requests.RequestException as exc:
        # URLs may contain Discord/ntfy credentials. Never print the exception URL.
        raise NotificationError(type(exc).__name__) from None


def send_ntfy(report: Report) -> None:
    card = report.buys[0]
    payload = {"topic": os.environ["NTFY_TOPIC"].strip(), "title": f"{card.badge}: {card.title}",
               "message": render_text(report), "priority": card.priority}
    if url := safe_url(card.url):
        payload["click"] = url
    headers = {}
    if token := os.environ.get("NTFY_TOKEN", "").strip():
        headers["Authorization"] = f"Bearer {token}"
    # JSON handles Unicode titles without trying to put them in HTTP headers.
    post(os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/"), json=payload, headers=headers)


def send_discord(report: Report) -> None:
    card = report.buys[0]
    embed = {"title": f"{card.badge}: {card.title}"[:256],
             "description": render_text(report)[:4096]}
    if url := safe_url(card.url):
        embed["url"] = url
    post(os.environ["DISCORD_WEBHOOK"].strip(), json={"embeds": [embed], "allowed_mentions": {"parse": []}})


def send_desktop(report: Report) -> None:
    card = report.buys[0]
    title = f"{card.badge}: {card.title}"
    # Put source facts before the long explanation: the actual listing title
    # must survive desktop truncation, not just the catalog name and price.
    body = f"{card.price}\n{'; '.join(card.facts)[:500]}\n{card.headline}\n{'; '.join(card.warnings)[:300]}"
    if notifier := shutil.which("terminal-notifier"):
        command = [notifier, "-title", title, "-message", body]
        if url := safe_url(card.url):
            command += ["-open", url]
    else:
        # A listing title is attacker-controlled. argv keeps it data rather than
        # executable AppleScript, including quotes and 'do shell script' text.
        command = ["osascript", "-e", "on run argv", "-e",
                   "display notification (item 1 of argv) with title (item 2 of argv)",
                   "-e", "end run", body, title]
    subprocess.run(command, check=True, capture_output=True, timeout=15)


def channels(*, email: bool, push: bool, dry_run: bool) -> tuple[Channel, ...]:
    if dry_run:
        return ()
    result = []
    if email:
        require_env("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")
        result.append(Channel("email", "email", send_email))
    if push:
        if os.environ.get("NTFY_TOPIC", "").strip():
            result.append(Channel("ntfy", "push", send_ntfy))
        if os.environ.get("DISCORD_WEBHOOK", "").strip():
            result.append(Channel("discord", "push", send_discord))
        desktop = os.environ.get("DESKTOP_NOTIFY", "").strip().lower()
        enabled = (desktop in ("1", "true", "yes", "on") or
                   desktop not in ("0", "false", "no", "off") and sys.platform == "darwin")
        if enabled:
            result.append(Channel("desktop", "push", send_desktop))
        if not any(channel.kind == "push" for channel in result) and not email:
            raise ValueError("Push-only run needs NTFY_TOPIC, DISCORD_WEBHOOK or DESKTOP_NOTIFY=1")
    # Urgent deliveries go first; SMTP may stall for a minute before failing.
    return tuple(sorted(result, key=lambda channel: channel.kind == "email"))
