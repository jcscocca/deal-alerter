"""Compatibility imports: canonical types and identity live elsewhere."""
from __future__ import annotations
from typing import Callable, Protocol
from dealcore.types import Listing, SourceError
from alerters.hardware.identity import group_id

class Source(Protocol):
    name: str
    fetch: Callable[[], list[Listing]]
