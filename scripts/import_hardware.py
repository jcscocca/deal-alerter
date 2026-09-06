"""Copy real domain bodies into this repo, deleting the duplicated workflow.

Usage: python scripts/import_hardware.py ../ai-deal-alerter
The source checkout is never modified; an existing destination is never replaced.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(text: str, replacements: dict[str, str], *, class_name: str = "") -> str:
    """Replace named definitions by source ranges, preserving every other comment."""
    tree, lines = ast.parse(text), text.splitlines(keepends=True)
    nodes = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == class_name).body if class_name else tree.body
    edits, found = [], set()
    for node in nodes:
        name = getattr(node, "name", None)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in replacements:
            found.add(name)
            first = min([node.lineno, *[d.lineno for d in getattr(node, "decorator_list", [])]])
            edits.append((first - 1, node.end_lineno, replacements[name]))
    if missing := replacements.keys() - found:
        raise ValueError(f"Original source shape changed; missing: {sorted(missing)}")
    for first, last, replacement in reversed(edits):
        lines[first:last] = [replacement + "\n"] if replacement else []
    return "".join(lines)


LOAD = """    @classmethod
    def load(cls, config_path: Path, watchlist_path: Path) -> "Config":
        raw = read_config(config_path)
        general, alerts, fit = raw.get("general", {}), raw.get("alerts", {}), raw.get("fit", {})
        return cls(
            ebay_client_id=os.environ.get("EBAY_CLIENT_ID", "").strip(),
            ebay_client_secret=os.environ.get("EBAY_CLIENT_SECRET", "").strip(),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", "").strip(),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", "").strip(),
            country=general.get("country", "US"),
            currency_symbol=general.get("currency_symbol", "$"),
            max_listing_age_hours=int(general.get("max_listing_age_hours", 72)),
            digest_at=alerts.get("digest_at", "GOOD"),
            push_at=alerts.get("push_at", "STRONG"),
            remind_after_days=int(alerts.get("remind_after_days", 7)),
            enforce_fit=bool(fit.get("enforce", False)),
            psu_headroom_w=int(fit.get("psu_headroom_w", 150)),
            hunts=load_watchlist(watchlist_path),
            thresholds=overlay(Thresholds(), raw.get("thresholds", {})))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()
    source, destination = args.checkout / "ada", ROOT / "alerters/hardware/native"
    required = ["catalog.py", "rig.py", "match.py", "history.py", "verdict.py", "config.py",
                "sources/__init__.py", "sources/base.py", "sources/ebay.py"]
    for relative in required:
        if not (source / relative).is_file():
            raise SystemExit(f"Missing original implementation: {source / relative}")
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite {destination}")
    if not (args.checkout / "requirements.txt").is_file():
        raise SystemExit("Original requirements.txt is needed to preserve the dependency footprint")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        work = Path(temporary) / "native"
        work.mkdir()
        (work / "__init__.py").write_text('"""Preserved hardware domain implementations."""\n')
        paths = [source / name for name in required[:6]] + list((source / "sources").rglob("*.py"))
        manifest = {}
        for path in paths:
            relative, text = path.relative_to(source), path.read_text(encoding="utf-8")
            manifest[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
            # Relative imports survive relocation. An absolute ada import needs
            # a deliberate edit, not a text replacement that changes Python binding.
            for node in ast.walk(ast.parse(text)):
                modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else
                           [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                if any(name == "ada" or name.startswith("ada.") for name in modules):
                    raise SystemExit(f"Relocate absolute ada import in {relative} before importing")
            if relative == Path("verdict.py"):
                text = rewrite(text, {"_ago": "from dealcore.verdict import ago as _ago",
                    "_fmt": 'def _fmt(amount: float) -> str:\n    return money(amount, whole_above=100)'})
                text += "\nfrom dealcore.verdict import money\n"
            if relative == Path("config.py"):
                text = rewrite(text, {"load_dotenv": "", "_desktop_notify_default": "",
                    "_check_required": "", "REQUIRED": "", "_thresholds_from": ""})
                transport_fields = "smtp_host smtp_port smtp_user smtp_password mail_from mail_to ntfy_topic ntfy_server ntfy_token discord_webhook desktop_notify".split()
                text = rewrite(text, {**dict.fromkeys(transport_fields, ""), "load": LOAD}, class_name="Config")
                text += "\nfrom dealcore.config import overlay, read_config\n"
            if relative == Path("sources/base.py"):
                text = ('"""Compatibility imports: canonical types and identity live elsewhere."""\n'
                        'from __future__ import annotations\n'
                        'from typing import Callable, Protocol\n'
                        'from dealcore.types import Listing, SourceError\n'
                        'from alerters.hardware.identity import group_id\n\n'
                        'class Source(Protocol):\n'
                        '    name: str\n'
                        '    fetch: Callable[[], list[Listing]]\n')
            compile(text, str(relative), "exec")
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        shutil.copyfile(args.checkout / "requirements.txt", work / "requirements.txt")
        (work / "MIGRATED.json").write_text(json.dumps(manifest, indent=2) + "\n")
        work.rename(destination)
    print(f"Imported domain bodies into {destination}; original checkout unchanged.")
    print("Install its requirements, copy config/watchlist/state as documented, then run the tests.")


if __name__ == "__main__":
    main()
