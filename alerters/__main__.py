"""Two explicit registrations, one workflow. No plugin discovery or rule language."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from dealcore.config import load_dotenv
from dealcore.notify import channels
from dealcore.run import run
from dealcore.state import AlertState
from .hardware.manual import CONDITIONS as MANUAL_CONDITIONS
from .hardware.plugin import HardwarePlugin
from .steam.plugin import SteamPlugin

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = {"steam": SteamPlugin, "hardware": HardwarePlugin}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", choices=PLUGINS)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state-dir", type=Path, default=ROOT / "state")
    parser.add_argument("--preview", type=Path)
    for flag in ("dry-run", "force", "all", "quiet-when-empty", "demo", "stats"):
        parser.add_argument(f"--{flag}", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fast", action="store_true", help="push only")
    modes.add_argument("--digest", action="store_true", help="email only")
    parser.add_argument("--fixture", type=Path, help="Steam API transcript; always a dry run")
    # Listings you found yourself. Recorded, then judged on every later run
    # exactly like a search hit; the URL is stored and never fetched.
    parser.add_argument("--add", metavar="URL", help="record a listing by hand and exit")
    parser.add_argument("--price", type=float, help="asking price for --add")
    parser.add_argument("--title", help="listing title for --add; the only evidence of what it is")
    parser.add_argument("--condition", default="unknown", choices=MANUAL_CONDITIONS)
    parser.add_argument("--sold", action="store_true", help="--add recorded a completed sale you witnessed")
    parser.add_argument("--note", default="", help="free text stored with an --add entry")
    args = parser.parse_args(argv)
    factory = PLUGINS[args.domain]
    if args.domain == "steam" and (args.fast or args.stats):
        parser.error("Steam supports digest mode, not --fast or --stats")
    if args.domain != "steam" and (args.demo or args.fixture):
        parser.error("The supplied offline transcript is for Steam only")
    if args.add is not None:
        if args.domain != "hardware":
            parser.error("--add records hardware listings only")
        if args.price is None or args.title is None:
            parser.error("--add needs --price and --title")
    elif args.price is not None or args.title is not None or args.sold:
        parser.error("--price, --title and --sold only mean something with --add")
    # Recording and reporting both stop short of delivery, so neither should
    # demand SMTP credentials the run will never use.
    dry = args.dry_run or args.demo or args.fixture is not None or args.stats or args.add is not None
    mode = "fast" if args.fast else "digest" if args.digest else factory.default_mode
    load_dotenv(ROOT / ".env")
    plugin = None
    try:
        # Requirements follow the selected mode. A preview must not demand SMTP,
        # and a broken email credential must not prevent a push-only run.
        delivery = channels(email=mode != "fast", push=mode != "digest", dry_run=dry)
        path = args.config or ROOT / "config" / f"{args.domain}.toml"
        if args.domain == "steam":
            fixture = ROOT / "examples/steam.json" if args.demo else args.fixture
            plugin = factory(path, args.state_dir, fixture=fixture)
        else:
            plugin = factory(path, args.state_dir, daily=mode != "fast")
        if args.add is not None:
            plugin.add_manual(url=args.add, price=args.price, title=args.title,
                              condition=args.condition, sold=args.sold, note=args.note)
            return 0
        if args.stats:
            plugin.show_stats()
            return 0
        options = replace(plugin.options, dry_run=dry, force=args.force,
                          include_others=args.all or args.demo or plugin.options.include_others,
                          quiet_when_empty=args.quiet_when_empty,
                          preview=args.preview or ROOT / f"report-{args.domain}.html")
        state = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
        # run owns closure from here, including exceptions and partial failures.
        running, plugin = plugin, None
        result = run(running, state, options, delivery)
        for problem in result.problems:
            print(problem, file=sys.stderr)
        print(f"{len(result.assessments)} assessed; {len(result.problems)} problem(s).")
        if dry:
            print(f"HTML preview: {options.preview}")
        return result.exit_code
    except (ValueError, OSError) as exc:
        # Do not dump transport exceptions: some include credential-bearing URLs.
        print(f"Configuration/state error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Run failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if plugin is not None:
            plugin.close()


if __name__ == "__main__":
    raise SystemExit(main())
