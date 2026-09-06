"""File tunables, environment secrets, and one source of truth for defaults."""
from __future__ import annotations

import os
import tomllib
from dataclasses import fields, replace
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def load_dotenv(path: Path) -> None:
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                # CI secrets must win over any developer's local file.
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def read_config(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def overlay(defaults: T, section: dict) -> T:
    known = {f.name for f in fields(defaults)}
    if unknown := section.keys() - known:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    values = {}
    for key, raw in section.items():
        kind = type(getattr(defaults, key))
        if kind is bool and not isinstance(raw, bool):
            raise ValueError(f"{key} must be a TOML boolean")
        if kind is int and isinstance(raw, float) and not raw.is_integer():
            raise ValueError(f"{key} must be an integer")
        values[key] = kind(raw)
    # Defaults come from the dataclass, never another set of loader literals.
    return replace(defaults, **values)


def require_env(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Missing environment settings: " + ", ".join(missing))
