"""Loopback-only shopping dashboard; only an explicit POST starts API research."""
from __future__ import annotations

import hmac
import json
import math
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dealcore.state import atomic_write
from alerters.hardware.prebuilt import gpu_model
from .research import PRESETS, capacity_mismatch, cpu_model
from .monitor_bridge import read_monitor
from .deal_overlap import combine_leads
from .facets import attributes

FRESH_SECONDS = 15 * 60
ASSETS = Path(__file__).with_name("web")
CATEGORIES = {"desktop-memory": "Desktops & memory", "tablets": "Tablets",
              "computers": "Computers", "supplies": "Tech supplies", "memory": "Memory",
              "monitor": "All deals", "amazon": "Amazon deals"}


def amount(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value < 1_000_000 else None


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result.timestamp() if result.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def walmart_snapshot(directory: Path, category: str, *, now=None, failed_at=None) -> dict:
    """Read only a known report file and project public shopping fields."""
    if category not in PRESETS:
        raise ValueError("Unknown category")
    now = time.time() if now is None else now
    result = {"category": category, "label": CATEGORIES[category], "checked_at": None,
              "expires_at": None, "fresh": False, "zip_code": None, "groups": [],
              "held": [], "problems": [], "coverage": [], "queries": [], "count": 0}
    path = directory / f"latest-{category}.json"
    if not path.exists():
        result["problems"] = ["No research saved for this category yet. Choose Check now to begin."]
        return result
    try:
        if path.stat().st_size > 4_000_000:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("category") != category or not isinstance(data.get("products"), list) or len(data["products"]) > 200:
            raise ValueError()
    except (OSError, ValueError, TypeError):
        result["problems"] = ["Saved research could not be read. Choose Check now to replace it."]
        return result
    checked = timestamp(data.get("observed_at"))
    fresh = checked is not None and 0 <= now - checked <= FRESH_SECONDS and (failed_at is None or checked > failed_at)
    result.update(checked_at=data.get("observed_at") if checked is not None else None,
                  expires_at=checked + FRESH_SECONDS if checked is not None else None,
                  fresh=fresh, zip_code=data.get("zip_code") if isinstance(data.get("zip_code"), str) else None)
    result["problems"] = [p for p in data.get("problems", []) if isinstance(p, str)][:20] if isinstance(data.get("problems"), list) else []
    result["queries"] = [q for q in data.get("queries", []) if isinstance(q, str)][:4] if isinstance(data.get("queries"), list) else []
    result["coverage"] = [{"query": str(c.get("query", "")),
                           "returned": c.get("returned") if type(c.get("returned")) is int else None,
                           "total": c.get("total") if type(c.get("total")) is int else None}
                          for c in data.get("coverage", []) if isinstance(c, dict)][:4] if isinstance(data.get("coverage"), list) else []
    groups, seen = {}, set()
    for raw in data["products"]:
        if not isinstance(raw, dict):
            continue
        item_id, title = raw.get("item_id"), raw.get("title")
        if not isinstance(item_id, str) or not item_id.isascii() or not item_id.isdigit() or len(item_id) > 20 or item_id in seen or not isinstance(title, str) or not title:
            continue
        seen.add(item_id)
        price, shipping = amount(raw.get("price")), amount(raw.get("shipping"))
        total = float(Decimal(str(price)) + Decimal(str(shipping))) if price is not None and shipping is not None else None
        fit = raw.get("memory_fit") if isinstance(raw.get("memory_fit"), dict) else {}
        model_gpu = gpu_model(title)
        ram = fit.get("installed_gb") if fit.get("installed_gb") in (32, 64) else None
        condition = raw.get("condition") if isinstance(raw.get("condition"), str) else "Not published"
        seller = raw.get("seller") if isinstance(raw.get("seller"), str) else "Not published"
        layout = fit.get("status") == "POSSIBLE REUSE"
        warnings = [w for w in raw.get("warnings", []) if isinstance(w, str)] if isinstance(raw.get("warnings"), list) else []
        queries = [q for q in raw.get("queries", []) if isinstance(q, str)] if isinstance(raw.get("queries"), list) else []
        key = raw.get("comparison_key")
        desktop_key = isinstance(key, list) and len(key) == 6 and key[0] == "desktop"
        row = {"id": item_id, "title": title, "url": f"https://www.walmart.com/ip/{item_id}",
               "seller": seller, "condition": condition, "price": price, "shipping": shipping,
               "total": total, "available": raw.get("available") is True, "gpu": model_gpu,
               "ram": ram, "potential": fit.get("potential_gb") if fit.get("potential_gb") in (96, 128) else None,
               "fit": fit.get("status") if isinstance(fit.get("status"), str) else "Not assessed",
               "fit_summary": fit.get("summary") if isinstance(fit.get("summary"), str) else "",
               "cpu": cpu_model(title) or "Not established",
               "storage": str(key[4]) if desktop_key else "Not established",
               "warnings": warnings, "layout_documented": layout, "rank": None, "reasons": []}
        if not fresh:
            row["reasons"].append("Last check failed" if failed_at is not None and checked is not None and checked <= failed_at else "Availability needs a new check")
        if not row["available"]:
            row["reasons"].append("Unavailable or unconfirmed at last check")
        if price is None or price <= 0:
            row["reasons"].append("Price unknown")
        if shipping is None:
            row["reasons"].append("Shipping unknown")
        if not seller.strip() or seller == "Not published" or not condition.strip() or condition == "Not published":
            row["reasons"].append("Seller or condition unknown")
        if capacity_mismatch(category, title, queries):
            row["reasons"].append("Storage variant differs from the search")
        if category == "desktop-memory" and (not model_gpu or not fit or fit.get("eligible") is not True or ram is None):
            row["reasons"].append(row["fit_summary"] or "Desktop configuration needs verification / owned-kit reference")
        if row["reasons"]:
            result["held"].append(row)
        else:
            group = f"RTX {model_gpu} · {ram}GB · {condition}" if category == "desktop-memory" else f"{condition} · price order"
            groups.setdefault(group, []).append(row)
    for name, rows in sorted(groups.items()):
        rows.sort(key=lambda row: (not row["layout_documented"] if category == "desktop-memory" else False, row["total"], row["id"]))
        for index, row in enumerate(rows, 1):
            row["rank"] = index
            row["why"] = ("Documented RAM layout first; " if row["layout_documented"] else "RAM layout still needs verification; ") + "ordered by total within this evidence level and GPU/RAM group." if category == "desktop-memory" else "Ordered by known total. Different models are not equivalent in performance or value."
        result["groups"].append({"name": name, "rows": rows})
    result["count"] = len(seen)
    return result


def snapshot(directory: Path, category: str, *, now=None, failed_at=None, monitor_runtime=None, deal_feeds=None) -> dict:
    if category not in CATEGORIES:
        raise ValueError("Unknown category")
    now = time.time() if now is None else now
    if category in ("monitor", "amazon"):
        result = {"category": category, "label": CATEGORIES[category], "checked_at": None,
                  "expires_at": None, "fresh": False, "zip_code": None, "groups": [],
                  "held": [], "problems": [], "coverage": [], "queries": [], "count": 0}
    else:
        result = walmart_snapshot(directory, category, now=now, failed_at=failed_at)
    rows = [row for group in result["groups"] for row in group["rows"]] + result["held"]
    for row in rows:
        row.update(source="walmart", retailer="Walmart", checked_at=result["checked_at"],
                   expires_at=result["expires_at"], lead=False, cost_note="price + shipping · before tax")
    result["sources"] = ([{"source": "walmart", "label": "Walmart", "jobs": 1,
                            "ready": int(result["fresh"]), "count": len(rows),
                            "checked_at": result["checked_at"], "truncated": False}]
                         if category not in ("monitor", "amazon") else [])
    monitor = read_monitor(monitor_runtime, category, now)
    rows += monitor["rows"]
    result["sources"] += monitor["sources"]
    if deal_feeds is not None:
        feeds = deal_feeds.snapshot(category, now)
        rows += feeds["rows"]
        result["sources"] += feeds["sources"]
    result["problems"] += monitor["problems"]
    result["monitor_connected"] = bool(monitor["sources"])
    result["groups"], result["held"], result["leads"] = [], [], []
    groups = {}
    for row in rows:
        if row.get("lead"):
            result["leads"].append(row)
        elif row["reasons"]:
            result["held"].append(row)
        else:
            name = (f"RTX {row['gpu']} · {row['ram']}GB · {row['condition']}" if category == "desktop-memory" else
                    f"{row.get('product_group', 'Products')} · {row['condition']} · price order" if category == "monitor" else
                    f"{row['condition']} · price order")
            groups.setdefault(name, []).append(row)
    for name, candidates in sorted(groups.items()):
        candidates.sort(key=lambda row: (not row["layout_documented"] if category == "desktop-memory" else False,
                                         row["total"], row["id"]))
        for rank, row in enumerate(candidates, 1):
            row["rank"] = rank
            row["why"] = ("Documented RAM layout first, then known total within this GPU/RAM/condition group."
                          if category == "desktop-memory" else "Known total within this group; unlike models are not equivalent in performance or value.")
        result["groups"].append({"name": name, "rows": candidates})
    result["report_count"] = len(result["leads"])
    result["leads"] = combine_leads(result["leads"])
    for row in [r for group in result["groups"] for r in group["rows"]] + result["held"] + result["leads"]:
        row["facets"] = attributes(row)
    result["overlap_count"] = result["report_count"] - len(result["leads"])
    result["count"] = len(rows) - result["overlap_count"]
    if monitor["sources"] or deal_feeds is not None:
        result["fresh"] = any(source["ready"] for source in result["sources"])
        dates = [row["checked_at"] for row in rows if timestamp(row.get("checked_at")) is not None]
        result["checked_at"] = max(dates, key=timestamp) if dates else result["checked_at"]
        result["expires_at"] = max((row.get("expires_at") or 0 for row in rows), default=0)
    return result


class Dashboard:
    def __init__(self, directory: Path, refresh, *, clock=time.time, cooldown=30, monitor_runtime=None, deal_feeds=None):
        self.directory, self.refresh, self.clock, self.cooldown = directory, refresh, clock, cooldown
        self.monitor_runtime = monitor_runtime
        self.deal_feeds = deal_feeds
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.running = None
        self.last_start = None
        self.receipt = directory / "dashboard-last-check.json"
        self.checks = {}
        try:
            if self.receipt.stat().st_size <= 8000:
                data = json.loads(self.receipt.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.checks = {key: {"status": value["status"], "at": value["at"]} for key, value in data.items() if key in PRESETS and isinstance(value, dict)
                                   and value.get("status") in ("checking", "success", "partial", "failed")
                                   and isinstance(value.get("at"), (int, float)) and not isinstance(value["at"], bool)
                                   and math.isfinite(value["at"]) and value["at"] >= 0}
        except (OSError, ValueError, TypeError):
            pass

    def state(self, category):
        with self.lock:
            job = self.checks.get(category, {})
            failed_at = job.get("at") if job.get("status") in ("failed", "checking") and self.running != category else None
            running = self.running
            remaining = max(0, self.cooldown - (self.clock() - self.last_start)) if self.last_start is not None else 0
        return {"snapshot": snapshot(self.directory, category, now=self.clock(), failed_at=failed_at, monitor_runtime=self.monitor_runtime, deal_feeds=self.deal_feeds),
                "running": running, "last_check": job, "retry_after": math.ceil(remaining), "fresh_seconds": FRESH_SECONDS}

    def start(self, category):
        if category in ("monitor", "amazon"):
            return 200, {"status": "Monitor results are read automatically; no extra retailer requests"}
        if category not in PRESETS:
            return 400, {"error": "Unknown category"}
        with self.lock:
            if self.running:
                return 409, {"error": "A shopping check is already running"}
            if self.last_start is not None and self.clock() - self.last_start < self.cooldown:
                return 429, {"error": "Please wait before starting another check"}
            started = self.clock()
            self.checks[category] = {"status": "checking", "at": started}
            try:
                atomic_write(self.receipt, json.dumps(self.checks))
            except OSError:
                self.checks.pop(category, None)
                return 503, {"error": "Cannot save the check status; no research started"}
            self.running, self.last_start = category, started
        threading.Thread(target=self._run, args=(category,), daemon=True).start()
        return 202, {"status": "checking"}

    def _run(self, category):
        try:
            code = self.refresh(category)
        except Exception:
            code = 2  # Never send exception text, settings paths or API bodies to the browser.
        with self.lock:
            self.checks[category] = {"status": "success" if code == 0 else "partial" if code == 1 else "failed", "at": self.clock()}
            try:
                atomic_write(self.receipt, json.dumps(self.checks))
            except OSError:
                self.checks[category]["status"] = "failed"
            self.running = None


def create_server(dashboard: Dashboard, port=8768):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def permitted(self, *, write=False):
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if host not in allowed or origin is not None and origin != "http://" + host:
                return False
            token = self.headers.get("X-TechScout-Token", "")
            return not write or (origin == "http://" + host and token.isascii() and hmac.compare_digest(token, dashboard.token))

        def send(self, status, body, kind="application/json; charset=utf-8"):
            content = json.dumps(body, allow_nan=False).encode() if isinstance(body, dict) else body
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if not self.permitted():
                return self.send(403, {"error": "Local origin required"})
            parsed = urlsplit(self.path)
            if parsed.path == "/api/state":
                category = parse_qs(parsed.query).get("category", ["desktop-memory"])[0]
                if category not in CATEGORIES:
                    return self.send(400, {"error": "Unknown category"})
                return self.send(200, dashboard.state(category))
            if parsed.path == "/health":
                return self.send(200, {"service": "TechScout", "status": "ok"})
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
                      "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8")}
            if parsed.path not in assets:
                return self.send(404, {"error": "Not found"})
            filename, kind = assets[parsed.path]
            content = (ASSETS / filename).read_bytes()
            if filename == "index.html":
                content = content.replace(b"__LOCAL_TOKEN__", dashboard.token.encode())
            self.send(200, content, kind)

        def do_POST(self):
            if not self.permitted(write=True):
                return self.send(403, {"error": "Local page authorization required"})
            if self.path != "/api/refresh":
                return self.send(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError()
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {"category"} or not isinstance(data["category"], str):
                    raise ValueError()
            except (ValueError, TypeError):
                return self.send(400, {"error": "Invalid request"})
            status, content = dashboard.start(data["category"])
            self.send(status, content)

    class LocalServer(ThreadingHTTPServer):
        # Windows SO_REUSEADDR permits two listeners on the same address, routing
        # requests to old/new dashboards unpredictably. Claim the port exclusively.
        allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = LocalServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(directory: Path, refresh, port=8768, *, monitor_runtime=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    from .deal_feeds import DealFeeds
    feeds = DealFeeds(directory)
    server = create_server(Dashboard(directory, refresh, monitor_runtime=monitor_runtime, deal_feeds=feeds), port)
    feeds.start()
    print(f"TechScout is ready at http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feeds.close()
        server.server_close()
