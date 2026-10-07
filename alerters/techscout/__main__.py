"""Run one local shopping session: python -m alerters.techscout."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dealcore.state import atomic_write
from .research import PRESETS, research
from .walmart import Credentials, WalmartClient, validate_zip


def local_directory() -> Path:
    base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / ".local" / "share"
    return base / "TechScout"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TechScout: one on-demand Walmart shopping report; no alerts or history.")
    parser.add_argument("--category", choices=PRESETS, default="desktop-memory")
    parser.add_argument("--query", action="append", help="Replace preset searches; repeat up to four times")
    parser.add_argument("--item-id", action="append", help="Replace saved candidate IDs; repeat up to 20 times")
    parser.add_argument("--limit", type=int, default=10, help="Results per search, 1-25 (default 10)")
    parser.add_argument("--settings", type=Path, default=local_directory() / "settings.json")
    parser.add_argument("--zip-code", help="Override the ZIP in local settings")
    parser.add_argument("--output", type=Path, default=local_directory() / "reports")
    args = parser.parse_args(argv)
    try:
        settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))["walmart"]
        zip_code = validate_zip(args.zip_code or settings["zip_code"])
        credential_file = Path(settings["credential_file"])
        if not credential_file.is_absolute():
            credential_file = args.settings.parent / credential_file
        credentials = Credentials.load(credential_file)
    except (OSError, ValueError, KeyError, TypeError):
        print("TechScout needs valid local Walmart settings, production credentials and a five-digit ZIP. "
              "See docs/techscout-shopping.md. No requests made.", file=sys.stderr)
        return 2
    events = []
    def record(event):
        events.append({"time": datetime.now(timezone.utc).isoformat(), "purpose": args.category, **event})
    client = WalmartClient(credentials, zip_code, audit=record)
    try:
        result = research(client, args.category, queries=args.query, seeds=args.item_id, limit=args.limit)
        args.output.mkdir(parents=True, exist_ok=True)
        stem = args.output / ("latest-" + args.category)
        atomic_write(stem.with_suffix(".html"), result.html())
        atomic_write(stem.with_suffix(".json"), json.dumps(result.document(), indent=2, ensure_ascii=False))
        # Overwrite a session receipt, never append prices or request history.
        atomic_write(stem.with_suffix(".requests.json"), json.dumps(events, indent=2))
        print(f"{len(result.products)} product cards; {client.requests} API calls. Report: {stem.with_suffix('.html')}")
        if result.problems or not result.products:
            print("Partial or empty research: check the report for coverage and access details.", file=sys.stderr)
            return 1
        return 0
    except (OSError, ValueError):
        # Avoid exposing credential paths or raw API data in error messages.
        print("TechScout could not validate the request or save the report. Check arguments and output permissions.", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
