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


def test_new_product_grace_survives_restart(tmp_path, monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(monitor.time, "time", lambda: clock[0])
    monkeypatch.setattr(monitor, "channels", lambda **_: ())
    runtime = tmp_path / "runtime"
    mon = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state",
                          runtime, dry_run=False)
    clock[0] += 3_600
    key = mon.add_product("https://www.newegg.com/p/3D5-000Z-002C6?Item=9SIA1HJKEB7402")
    assert mon.jobs[key]["created_at"] == clock[0]
    mon.write_health()
    clock[0] += 601
    restarted = monitor.Monitor(monitor.ROOT / "config/monitor.toml", tmp_path / "state",
                                runtime, dry_run=False)
    assert restarted.jobs[key]["created_at"] == 13_600
    status = {"heartbeat": clock[0], "started": restarted.started,
              "jobs": {key: restarted.jobs[key]}}
    assert monitor.health_problems(status, clock[0]) == [f"{key}: no successful check"]
