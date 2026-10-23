import json
from alerters.hardware import monitor
from alerters.hardware.monitor_sources import Batch


def test_continuous_polling_cannot_starve_later_products(tmp_path, monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(monitor.time, "time", lambda: clock[0])
    monkeypatch.setattr(monitor.random, "uniform", lambda *_: 0)
    mon = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state",
                          tmp_path / "runtime", dry_run=True)
    mon.jobs.clear()
    mon.cfg["workers"] = 2
    products = [mon.add_job("newegg", 120, f"https://www.newegg.com/p/{index}")
                for index in range(6)]
    other_host = mon.add_job("hp", 120, "https://www.hp.com/product")
    deferred = mon.add_job("newegg", 120, "https://www.newegg.com/p/backoff")
    mon.jobs[deferred].update(next=12_000, failures=1, error="Host is backing off")
    processed = []
    active = []

    class Future:
        def __init__(self, job):
            self.host = job["url"].split("/")[2]
            self.ready_at = clock[0] + 60

        def done(self):
            return clock[0] >= self.ready_at

        def result(self):
            assert self.done()
            return Batch()

    class Executor:
        def __init__(self, *, max_workers, **_):
            self.workers = max_workers

        def submit(self, fetch, job, *_):
            running = [future for future in active if not future.done()]
            future = Future(job)
            assert len(running) < self.workers
            assert all(other.host != future.host for other in running)
            active.append(future)
            return future

        def shutdown(self, **_):
            pass

    def tick(_):
        clock[0] += 15
        if clock[0] >= 10_780:
            mon.stopping = True

    monkeypatch.setattr(monitor, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(monitor.time, "sleep", tick)
    monkeypatch.setattr(mon, "process", lambda key, _: processed.append(key))
    monkeypatch.setattr(mon, "recheck_starts", lambda: None)
    monkeypatch.setattr(mon, "digest", lambda _: None)
    monkeypatch.setattr(mon, "write_health", lambda: None)

    assert mon.loop() == 1  # The existing backoff remains visible.
    assert all(processed.count(key) >= 2 for key in products)
    assert processed[:2] == [products[0], other_host]
    assert deferred not in processed
    assert mon.jobs[deferred]["next"] == 12_000


def test_feed_schedule_grace_survives_restart(tmp_path, monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(monitor.time, "time", lambda: clock[0])
    monkeypatch.setattr(monitor, "channels", lambda **_: ())
    runtime = tmp_path / "runtime"
    mon = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state",
                          runtime, dry_run=False)
    clock[0] += 3_600
    key = next(key for key, job in mon.jobs.items() if job["kind"] == "reddit")
    mon.jobs[key]["created_at"] = clock[0]
    assert mon.jobs[key]["created_at"] == clock[0]
    mon.write_health()
    clock[0] += 3 * monitor.NEWEGG_SECONDS + 1
    restarted = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state",
                                runtime, dry_run=False)
    assert restarted.jobs[key]["created_at"] == 13_600
    status = {"heartbeat": clock[0], "started": restarted.started,
              "jobs": {key: restarted.jobs[key]}}
    assert monitor.health_problems(status, clock[0]) == [f"{key}: no successful check"]


def test_no_complete_pc_product_or_discovery_jobs_are_scheduled(tmp_path):
    mon = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=True)
    newegg = [job for job in mon.jobs.values() if job["kind"] in ("newegg", "discover-newegg")]
    assert not newegg
    assert {job["kind"] for job in mon.jobs.values()} <= {"reddit", "slickdeals", "legacy"}


def test_hp_is_retired_even_from_a_saved_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "channels", lambda **_: ())
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "schedule.json").write_text(json.dumps({"jobs": {"hp-saved": {
        "kind": "hp", "url": "https://www.hp.com/us-en/shop/pdp/omen-example"}}}))
    mon = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state", runtime, dry_run=False)
    assert mon.client.hp_reader is None
    assert not [job for job in mon.jobs.values() if job["kind"] in ("hp", "discover-hp")]
    assert mon.add_product("https://www.hp.com/us-en/shop/pdp/omen-example") is None
    assert not any("HP" in problem for problem in mon.problems)
