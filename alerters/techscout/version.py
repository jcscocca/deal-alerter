"""A public build fingerprint, cached by each running dashboard instance."""
from __future__ import annotations

import hashlib
from pathlib import Path


def app_version(root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for folder in ("alerters", "dealcore", "config"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html", ".toml"}:
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
    return "standout-v3-" + digest.hexdigest()[:20]
