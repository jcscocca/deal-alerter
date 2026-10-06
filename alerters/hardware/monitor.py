"""One Windows-compatible hardware state writer, with independent fetch jobs.

    python -m alerters.hardware.monitor --once --dry-run
    python -m alerters.hardware.monitor --status

Real operation requires a cutover owner manifest. Preparation never enables it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import random
import signal
import sys
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

from dealcore.config import load_dotenv
from dealcore.locking import WriterLock
from dealcore.notify import channels
from dealcore.run import run
from dealcore.state import AlertState, atomic_write
from dealcore.types import Card, FetchResult, Report
from .monitor_sources import Batch, fetch_job
from .community import SLICKDEALS_COMPUTERS, SLICKDEALS_COVERAGE
from .prebuilt import OfferState
from .prebuilt_plugin import MonitorHardwarePlugin, community_offer, offer_listing
from .retailers import canonical_product
from .retail_http import Deferred, PublicClient, public_url

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = Path(os.environ.get("PROGRAMDATA", ROOT / ".local")) / "DealAlerter"
LOG = logging.getLogger("hardware-monitor")
HEALTH_CHANGE_SECONDS = 30 * 60
HEALTH_REMINDER_SECONDS = 24 * 3600


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def job_id(kind: str, url: str = "") -> str:
    return kind + "-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def failure_delay(failures: int, interval: float, retry: float = 0, maximum: float = 3600) -> float:
    # A server's Retry-After is never shortened by our maximum backoff.
    return max(retry, min(maximum, interval * 2 ** min(failures, 10)))


def check_owner(runtime: Path, state_root: Path):
    owner = read_json(runtime / "owner.json", {})
    if owner.get("hardware_writer") != "thinkpad" or not owner.get("approved"):
        raise ValueError("Local hardware cutover has not been approved/enabled")
    if Path(owner.get("state_root", "")).resolve() != state_root.resolve():
        raise ValueError("State directory differs from the approved owner manifest")
    if Path(owner.get("checkout", "")).resolve() != ROOT.resolve():
        raise ValueError("Checkout differs from the approved owner manifest")


def health_problems(status: dict, now: float, stale: int = 600) -> list[str]:
    problems = []
    heartbeat = status.get("heartbeat", 0)
    if now - heartbeat > 90:
        problems.append("Monitor heartbeat is stale")
    for key, job in status.get("jobs", {}).items():
        limit = max(stale, job["interval"] * 3)
        if not job.get("last_success") and now - status.get("started", 0) > limit:
            problems.append(f"{key}: no successful check")
        elif job.get("last_success") and now - job["last_success"] > limit:
            problems.append(f"{key}: checks stale ({job.get('error') or 'no result'})")
        elif job.get("error"):
            problems.append(f"{key}: {job['error']}")
    problems.extend(status.get("problems", []))
    return problems


def health_problem_key(problem: str, status: dict) -> str:
    if problem == "Monitor heartbeat is stale":
        return "monitor:heartbeat"
    prefix = problem.partition(":")[0]
    if prefix in status.get("jobs", {}):
        # Backoff, missing success and stale checks describe the same job outage.
        return "job:" + prefix
    return "coverage:" + problem


class Monitor:
    def __init__(self, config: Path, state_root: Path, runtime: Path, *, dry_run: bool):
        self.config_path, self.state_root, self.runtime, self.dry_run = config, state_root, runtime, dry_run
        self.config = tomllib.loads(config.read_text(encoding="utf-8"))
        self.cfg = self.config["monitor"]
        for name, minimum in (("retailer_seconds", 60), ("feed_seconds", 180), ("discovery_seconds", 300), ("legacy_seconds", 900)):
            if self.cfg[name] < minimum:
                raise ValueError(f"{name} must be at least {minimum}")
        if not 1 <= self.cfg["workers"] <= 12 or not 1 <= self.cfg["max_products_per_retailer"] <= 100:
            raise ValueError("Invalid monitor concurrency/product limit")
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.client = PublicClient()
        self.jobs = {}
        self.pending, self.cache, self.benchmarks = {}, {}, []
        self.started = time.time()
        self.problems = [SLICKDEALS_COVERAGE]
        self.results = []
        self.last_digest = ""
        self.stopping = False
        self.delivery = channels(email=False, push=True, dry_run=dry_run)
        for seed in self.config.get("seed", []):
            self.add_product(seed["url"])
        for discovery in self.config.get("discovery", []):
            public_url(discovery["url"])
            self.add_job(discovery["kind"], self.cfg["discovery_seconds"], discovery["url"])
        for name in ("reddit", "slickdeals"):
            self.add_job(name, self.cfg["feed_seconds"], SLICKDEALS_COMPUTERS if name == "slickdeals" else "")
        for name, interval in (("ebay", self.cfg["legacy_seconds"]), ("apple-refurb", 3600)):
            if name == "ebay" and not (os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET")):
                self.problems.append("eBay disabled: local credentials missing")
                continue
            key = self.add_job("legacy", interval, name)
            self.jobs[key].update(source=name, config=str(ROOT / "config/hardware.toml"))
        saved = read_json(runtime / "schedule.json", {"jobs": {}}) if not dry_run else {"jobs": {}}
        self.last_digest = saved.get("last_digest", "")
        for name, deadline in saved.get("host_backoff", {}).items():
            self.client.host(name)["blocked_until"] = deadline
        for key, old in saved["jobs"].items():
            if key not in self.jobs and old.get("kind") in ("hp", "newegg"):
                self.add_product(old["url"])
            if key in self.jobs:
                for field in ("last_success", "next", "failures", "error"):
                    if field in old:
                        self.jobs[key][field] = old[field]
        self.write_health()

    def add_job(self, kind, interval, url=""):
        key = job_id(kind, url)
        self.jobs.setdefault(key, {"kind": kind, "url": url, "interval": interval, "next": 0,
                                   "failures": 0, "last_success": 0, "error": ""})
        return key

    def add_product(self, url):
        url = canonical_product(url)
        kind = "hp" if "www.hp.com/" in url else "newegg"
        key = job_id(kind, url)
        count = sum(j["kind"] == kind for j in self.jobs.values())
        if key not in self.jobs and count >= self.cfg["max_products_per_retailer"]:
            message = f"{kind}: discovery cap reached; expand reviewed product limit for full coverage"
            if message not in self.problems:
                self.problems.append(message)
            return None
        return self.add_job(kind, self.cfg["retailer_seconds"], url)

    def process(self, key: str, batch: Batch):
        now = datetime.now(timezone.utc)
        listings = []
        for listing in batch.listings:
            offer = community_offer(listing) if listing.source.startswith(("reddit", "slickdeals")) else None
            if offer:
                listings.append(offer_listing(offer))
                try:
                    self.add_product(offer.url)
                except ValueError:
                    pass
            else:
                listings.append(listing)
        listings.extend(offer_listing(offer) for offer in batch.offers)
        for url in batch.discovered:
            self.add_product(url)
        plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", self.state_root, daily=False, now=now)
        plugin.sources = (type("FetchedBatch", (), {"name": key, "fetch": lambda _: FetchResult(listings)})(),)
        # Fresh comparable loose-GPU evidence survives separate retailer/feed jobs,
        # but expires after 20 minutes. It is never used as PC price history.
        benchmark = [item for stamp, item in self.benchmarks if time.time() - stamp <= 1200]
        original_promote = plugin.promote
        def promote(items):
            selected = {item.key for item in items}
            return [item for item in original_promote(items + [b for b in benchmark if b.key not in selected]) if item.key in selected]
        plugin.promote = promote
        state = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
        preview = self.runtime / "previews" / f"{key}.html"
        options = replace(plugin.options, dry_run=self.dry_run, quiet_when_empty=True, preview=preview)
        result = run(plugin, state, options, self.delivery, now=now)
        for item in result.assessments:
            if item.loggable and not item.detail.is_system and not item.detail.is_bundle:
                self.benchmarks = [(stamp, old) for stamp, old in self.benchmarks if old.key != item.key and time.time() - stamp <= 1200]
                self.benchmarks.append((time.time(), item))
        self.cache[key] = (time.time(), listings)
        # Successful exact retailer verification resolves any earlier community
        # start recheck without modifying the original announcement's receipt.
        for offer in batch.offers:
            if offer.confirmed and offer.sale_status(now) == "live":
                for row in plugin.offers.rows.values():
                    if row["offer"].get("announcement") and row["offer"].get("url") == offer.url:
                        row["confirmed_offer_key"] = offer.key
                if not self.dry_run:
                    plugin.offers.save()
        notes = batch.notes + result.problems
        for offer in batch.offers:
            if not offer.confirmed or offer.total(now) is None:
                notes.append("Offer found but seller/configuration/landed total cannot be confirmed")
        self.results.append({"job": key, "offers": len(batch.offers), "listings": len(listings),
                             "assessed": len(result.assessments), "notes": notes})
        self.results = self.results[-100:]
        if result.problems:
            raise Deferred("Assessment/delivery failed: " + "; ".join(result.problems), 120)
        if notes and batch.offers:
            raise Deferred("; ".join(notes), 300)

    def recheck_starts(self):
        store = OfferState(self.state_root / "hardware/US")
        for identity, offer in store.due_announcements(datetime.now(timezone.utc)):
            try:
                key = self.add_product(offer.url)
            except ValueError:
                # Unknown retailer: recheck community feed, never claim confirmation.
                for job in self.jobs.values():
                    if job["kind"] in ("reddit", "slickdeals"):
                        job["next"] = min(job["next"], time.time())
                key = None
            if key:
                job = self.jobs[key]
                # Respect source failure backoff and published host Retry-After.
                if not job["failures"]:
                    job["next"] = min(job["next"], time.time())
            store.rows[identity]["start_rechecked"] = datetime.now(timezone.utc).isoformat()
        if not self.dry_run:
            store.save()

    def digest(self, now: datetime):
        hour, minute = map(int, self.cfg["digest_utc"].split(":"))
        day = now.date().isoformat()
        if self.dry_run or (now.hour, now.minute) < (hour, minute) or self.last_digest == day:
            return
        try:
            email = channels(email=True, push=False, dry_run=False)
        except ValueError:
            message = "Hardware digest unavailable: local SMTP credentials missing"
            if message not in self.problems:
                self.problems.append(message)
            return
        # A fresh cache avoids duplicate network bursts. Expired offers cannot
        # silently be mailed after an outage. Digest retries only failed receipts.
        rows = [row for stamp, entries in self.cache.values() if time.time() - stamp < 1200 for row in entries]
        if not rows:
            return
        plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", self.state_root, daily=True, now=now)
        plugin.sources = (type("Cached", (), {"name": "digest-cache", "fetch": lambda _: FetchResult(rows)})(),)
        state = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
        result = run(plugin, state, replace(plugin.options, quiet_when_empty=True), email, now=now)
        if not result.problems:
            self.last_digest = day

    def write_health(self):
        value = {"version": 1, "pid": os.getpid(), "started": self.started, "heartbeat": time.time(),
                 "dry_run": self.dry_run, "jobs": self.jobs, "problems": self.problems, "results": self.results}
        atomic_write(self.runtime / "health.json", json.dumps(value, indent=2) + "\n")
        if not self.dry_run:
            atomic_write(self.runtime / "schedule.json", json.dumps({"jobs": self.jobs, "last_digest": self.last_digest,
                         "host_backoff": {host: value.get("blocked_until", 0) for host, value in self.client.hosts.items()}}, indent=2) + "\n")

    def loop(self, *, once=False):
        executor = ThreadPoolExecutor(max_workers=self.cfg["workers"], thread_name_prefix="fetch")
        initial = set(self.jobs)
        completed = set()
        last_heartbeat = 0
        try:
            while not self.stopping:
                now = time.time()
                for future, key in list(self.pending.items()):
                    if not future.done():
                        continue
                    del self.pending[future]
                    job = self.jobs[key]
                    try:
                        self.process(key, future.result())
                        job.update(last_success=time.time(), failures=0, error="")
                        delay = job["interval"]
                        LOG.info("%s checked", key)
                    except Exception as exc:
                        # Never log raw network exceptions or credential-bearing URLs.
                        reason = str(exc) if isinstance(exc, Deferred) else type(exc).__name__
                        job.update(failures=job["failures"] + 1, error=reason)
                        delay = failure_delay(job["failures"], job["interval"], getattr(exc, "seconds", 0), self.cfg["max_backoff_seconds"])
                        LOG.warning("%s %s; retry in %.0fs", key, reason, delay)
                    job["next"] = time.time() + delay + random.uniform(0, min(5, delay * .05))
                    completed.add(key)
                if once and initial <= completed and not self.pending:
                    break
                self.recheck_starts()
                busy = set(self.pending.values())
                # Seeds first, then community/discovery. Slow hosts do not consume
                # all workers: at most one in-flight public request job per host.
                busy_hosts = {self.jobs[k].get("url", "").split("/")[2] for k in busy if self.jobs[k].get("url", "").startswith("https://")}
                for key, job in list(self.jobs.items()):
                    if len(self.pending) >= self.cfg["workers"]:
                        break
                    if key in busy or job["next"] > now or (once and (key in completed or key not in initial)):
                        continue
                    host = job["url"].split("/")[2] if job["url"].startswith("https://") else key
                    if host in busy_hosts:
                        continue
                    self.pending[executor.submit(fetch_job, dict(job), self.client, self.config.get("coupon", []))] = key
                    busy_hosts.add(host)
                if not once:
                    self.digest(datetime.now(timezone.utc))
                if now - last_heartbeat >= self.cfg["heartbeat_seconds"]:
                    self.write_health()
                    last_heartbeat = now
                time.sleep(.5)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            self.write_health()
        return 1 if any(j["error"] for j in self.jobs.values()) else 0


def watchdog(runtime: Path, *, dry_run: bool):
    status = read_json(runtime / "health.json", {})
    now = time.time()
    issues = health_problems(status, now)
    prior_health = read_json(runtime / "watchdog.json", {})
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "problems": issues}
    atomic_write(runtime / "watchdog.json", json.dumps(result, indent=2) + "\n")
    if dry_run:
        print(json.dumps(result, indent=2))
        return bool(issues)
    owner = read_json(runtime / "owner.json", {})
    check_owner(runtime, Path(owner.get("state_root", "")))
    if time.time() - status.get("heartbeat", 0) > 120:
        # Restart independently of the network/notification transport.
        import subprocess
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for action in ("/End", "/Run"):
            subprocess.run(["schtasks.exe", action, "/TN", "DealAlerter-Hardware"], capture_output=True,
                           timeout=20, creationflags=flags, check=action == "/Run")
    receipt_path = runtime / "watchdog-receipt.json"
    previous = read_json(receipt_path, {})
    original = json.dumps(previous, sort_keys=True)
    keys = sorted({health_problem_key(problem, status) for problem in issues})
    # Migrate delivered legacy fingerprints without sending the same warning
    # again just because the receipt format changed.
    prior_issues = prior_health.get("problems", [])
    prior_fingerprint = hashlib.sha256(json.dumps(sorted(prior_issues)).encode()).hexdigest()
    for name, record in list(previous.items()):
        if name in ("fingerprint", "sent_at", "version"):
            continue
        if isinstance(record, str):
            reported = [health_problem_key(problem, status) for problem in prior_issues] if record == prior_fingerprint else []
            record = {"problem_keys": reported, "sent_at": previous.get("sent_at", 0)}
        if isinstance(record, dict):
            # Remember recovery even while other coverage warnings remain. A
            # later lost heartbeat must be able to alert immediately again.
            record["problem_keys"] = sorted(set(record.get("problem_keys", [])) & set(keys))
            previous[name] = record
    # Persist recovery before attempting delivery: an offline second transport
    # must not prevent the successful transport from recognizing a new outage.
    if previous and json.dumps(previous, sort_keys=True) != original:
        atomic_write(receipt_path, json.dumps(previous) + "\n")
    fingerprint = hashlib.sha256(json.dumps(sorted(issues)).encode()).hexdigest()
    if issues:
        stale = "monitor:heartbeat" in keys
        report = Report("Hardware monitor heartbeat is stale" if stale else "Hardware monitor coverage needs attention",
                        "Monitoring health", "", "",
                        (Card("ThinkPad hardware monitor", "", "", "MONITOR STALE" if stale else "COVERAGE DEGRADED",
                              "Heartbeat needs attention" if stale else "Monitor running; some checks need attention",
                              "; ".join(issues), priority=4 if stale else 2),))
        for channel in channels(email=False, push=True, dry_run=False):
            record = previous.get(channel.name, {})
            new = set(keys) - set(record.get("problem_keys", []))
            elapsed = now - record.get("sent_at", 0)
            changed_due = bool(new) and elapsed >= HEALTH_CHANGE_SECONDS
            if (not record or "monitor:heartbeat" in new or changed_due or elapsed >= HEALTH_REMINDER_SECONDS):
                channel.send(report)
                previous[channel.name] = {"problem_keys": keys, "sent_at": now}
                previous.update(version=2, fingerprint=fingerprint, sent_at=now)
                atomic_write(receipt_path, json.dumps(previous) + "\n")
    # Delivery times survive recovery; coverage flapping cannot reset the limit.
    # The diagnostics above still update on every watchdog check.
    return bool(issues)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/monitor.toml")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "state")
    parser.add_argument("--runtime", type=Path, default=ROOT / ".local/monitor-dry-run")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--watchdog", action="store_true")
    args = parser.parse_args(argv)
    load_dotenv(args.env_file)
    if args.status:
        status = read_json(args.runtime / "health.json", {})
        issues = health_problems(status, time.time())
        print(json.dumps({"problems": issues, "jobs": status.get("jobs", {})}, indent=2))
        return int(bool(issues))
    args.runtime.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.runtime / "monitor.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    try:
        if args.watchdog:
            return int(watchdog(args.runtime, dry_run=args.dry_run))
        if not args.dry_run:
            check_owner(args.runtime, args.state_dir)
        lock = args.runtime / "dry-run.lock" if args.dry_run else args.state_dir / "hardware/.writer.lock"
        with WriterLock(lock):
            monitor = Monitor(args.config, args.state_dir, args.runtime, dry_run=args.dry_run)
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: setattr(monitor, "stopping", True))
            return monitor.loop(once=args.once)
    except Exception as exc:
        LOG.error("Monitor failed: %s", type(exc).__name__)
        if sys.stderr:
            print(f"Monitor failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
