"""Bounded, signed calls to Walmart's documented affiliate search/lookup APIs."""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import requests

BASE = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2/"
MAX_RESPONSE = 4_000_000


class WalmartError(RuntimeError):
    """Safe to display: never includes response bodies, credentials or headers."""


def validate_zip(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{5}", value):
        raise ValueError("Walmart requires an explicit five-digit ZIP code")
    return value


def item_ids(values) -> list[str]:
    result = list(dict.fromkeys(str(value) for value in values))
    if not result or any(not re.fullmatch(r"[0-9]{1,20}", value) for value in result):
        raise ValueError("Item IDs must be numeric Walmart product IDs")
    if len(result) > 20:
        raise ValueError("A lookup supports at most 20 distinct item IDs")
    return result


def response_items(data: dict) -> list[dict]:
    # The documented example uses an envelope; the live single-item API also
    # returns the product directly. Neither shape means a successful empty list.
    if not isinstance(data, dict):
        raise WalmartError("Unexpected Walmart response format")
    rows = [data] if "itemId" in data else data.get("items")
    if rows is None and data.get("totalResults") == 0:
        rows = []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise WalmartError("Unexpected Walmart product list")
    return rows


@dataclass(repr=False)
class Credentials:
    consumer_id: str = field(repr=False)
    key_version: str
    private_key: object = field(repr=False)

    @classmethod
    def load(cls, path: Path):
        try:
            from cryptography.exceptions import UnsupportedAlgorithm
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        except ImportError:
            raise ValueError("Install requirements-techscout.txt to enable Walmart signing") from None
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("environment") != "PRODUCTION":
                raise ValueError()
            consumer_id = str(UUID(data["consumer_id"]))
            version = str(data["key_version"])
            if not re.fullmatch(r"[1-9][0-9]*", version):
                raise ValueError()
            key_path = Path(data["private_key_path"])
            if not key_path.is_absolute():
                key_path = path.parent / key_path
            if key_path.stat().st_size > 100_000:
                raise ValueError()
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
                raise ValueError()
            return cls(consumer_id, version, key)
        except (ValueError, KeyError, TypeError, OSError, UnsupportedAlgorithm):
            raise ValueError("Cannot load the local Walmart production RSA credential") from None

    def headers(self, timestamp: str) -> dict[str, str]:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        # Walmart's existing SHA256WithRSA protocol requires PKCS#1 v1.5.
        canonical = f"{self.consumer_id}\n{timestamp}\n{self.key_version}\n".encode()
        signature = self.private_key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
        return {"WM_CONSUMER.ID": self.consumer_id, "WM_CONSUMER.INTIMESTAMP": timestamp,
                "WM_SEC.KEY_VERSION": self.key_version,
                "WM_SEC.AUTH_SIGNATURE": base64.b64encode(signature).decode(),
                "Accept": "application/json", "User-Agent": "TechScout/1.0"}


class WalmartClient:
    def __init__(self, credentials: Credentials, zip_code: str, *, audit=None, session=None,
                 max_requests: int = 12, clock=time.time):
        self.credentials = credentials
        self.zip_code = validate_zip(zip_code)
        self.session = session or requests.Session()
        # Never pick up unrelated .netrc authentication or environment secrets.
        self.session.trust_env = False
        self.audit = audit or (lambda event: None)
        self.max_requests = max_requests
        self.requests = 0
        self.clock = clock
        self.cache = {}
        self.stopped = False

    def close(self):
        self.session.close()

    def _request(self, operation: str, params: dict) -> dict:
        if operation not in {"search", "items"}:
            raise ValueError("Unsupported Walmart operation")
        key = (operation, tuple(sorted(params.items())))
        event = {"operation": operation, "parameters": dict(params), "cached": key in self.cache}
        if key in self.cache:
            self.audit({**event, "status": "cached"})
            return self.cache[key]
        if self.stopped or self.requests >= self.max_requests:
            raise WalmartError("Walmart research request limit reached or access is unavailable")
        self.requests += 1
        status = "connection_error"
        try:
            with self.session.get(BASE + operation, params=params,
                                  headers=self.credentials.headers(str(int(self.clock() * 1000))),
                                  timeout=(10, 30), allow_redirects=False, stream=True) as response:
                status = response.status_code
                if status != 200:
                    if status in {401, 403, 429}:
                        self.stopped = True
                    raise WalmartError(f"Walmart {operation} returned HTTP {status}; no automatic retry")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise WalmartError("Walmart response exceeded the size limit")
                    chunks.append(chunk)
                try:
                    data = json.loads(b"".join(chunks))
                except (ValueError, UnicodeError):
                    raise WalmartError("Walmart returned invalid JSON") from None
                if not isinstance(data, dict):
                    raise WalmartError("Unexpected Walmart response format")
                self.cache[key] = data
                return data
        except requests.RequestException:
            raise WalmartError("Walmart connection failed; no automatic retry") from None
        finally:
            self.audit({**event, "status": status})

    def search(self, query: str, limit: int = 10) -> tuple[list[dict], int | None]:
        query = query.strip()
        if not query or len(query) > 200 or not 1 <= limit <= 25:
            raise ValueError("Search needs 1-200 characters and a limit between 1 and 25")
        # Search is discovery only; localized prices come from a later lookup.
        data = self._request("search", {"query": query, "numItems": limit,
                                        "responseGroup": "full", "sort": "relevance"})
        rows = response_items(data)
        total = data.get("totalResults")
        return rows[:limit], total if isinstance(total, int) and not isinstance(total, bool) else None

    def lookup(self, ids) -> list[dict]:
        ids = item_ids(ids)
        data = self._request("items", {"ids": ",".join(ids), "zipCode": self.zip_code})
        rows = response_items(data)
        if any(str(row.get("itemId")) not in ids for row in rows):
            raise WalmartError("Walmart returned an unrequested product ID")
        return rows
