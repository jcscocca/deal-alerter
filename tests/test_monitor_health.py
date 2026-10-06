import hashlib
import json

import pytest

from alerters.hardware import monitor
from dealcore.notify import Channel


@pytest.fixture
def health_watchdog(tmp_path, monkeypatch):
    clock = [10_000.0]
    sent = []
    monkeypatch.setattr(monitor.time, "time", lambda: clock[0])
    monkeypatch.setattr(monitor, "check_owner", lambda *_: None)
    monkeypatch.setattr(monitor, "channels", lambda **_: (Channel("ntfy", "push", sent.append),))
    monkeypatch.setattr("subprocess.run", lambda *_, **__: None)

    def check(*, jobs=None, problems=None, heartbeat=None):
        status = {"heartbeat": clock[0] if heartbeat is None else heartbeat,
                  "started": 10_000.0, "jobs": jobs or {}, "problems": problems or []}
        (tmp_path / "health.json").write_text(json.dumps(status))
        monitor.watchdog(tmp_path, dry_run=False)
        return json.loads((tmp_path / "watchdog.json").read_text())

    return tmp_path, clock, sent, check


def failed_job(error="Network request failed"):
    return {"interval": 120, "last_success": 0, "error": error}


def test_error_wording_and_stale_transition_do_not_repeat_an_outage(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    check(jobs=jobs)
    clock[0] += 60
    jobs["hp-example"]["error"] = "Host is backing off"
    assert "backing off" in check(jobs=jobs)["problems"][0]
    clock[0] += 600
    assert "no successful check" in check(jobs=jobs)["problems"][0]
    assert len(sent) == 1
    assert sent[0].buys[0].priority == 2
    assert sent[0].buys[0].badge == "COVERAGE DEGRADED"
    assert "Monitor running" in sent[0].buys[0].headline


def test_staggered_product_failures_are_batched_and_unchanged_warnings_remind_daily(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    check(jobs=jobs)
    for minute in range(1, 13):
        clock[0] = 10_000 + minute * 60
        jobs[f"newegg-{minute}"] = failed_job("Offer cannot be confirmed")
        check(jobs=jobs)
    assert len(sent) == 1
    clock[0] = 10_000 + monitor.HEALTH_CHANGE_SECONDS - 1
    check(jobs=jobs)
    assert len(sent) == 1
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 2
    assert "newegg-12" in sent[-1].buys[0].reason
    last_sent = clock[0]
    clock[0] = last_sent + monitor.HEALTH_REMINDER_SECONDS - 1
    check(jobs=jobs)
    assert len(sent) == 2
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 3


def test_lost_heartbeat_bypasses_coverage_interval_and_can_alert_after_partial_recovery(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    check(jobs=jobs)
    clock[0] += 60
    check(jobs=jobs, heartbeat=clock[0] - 100)
    assert len(sent) == 2
    assert sent[-1].buys[0].badge == "MONITOR STALE"
    assert sent[-1].buys[0].priority == 4
    clock[0] += 60
    check(jobs=jobs, heartbeat=clock[0] - 100)
    assert len(sent) == 2
    clock[0] += 60
    check(jobs=jobs)
    assert len(sent) == 2
    clock[0] += 60
    check(jobs=jobs, heartbeat=clock[0] - 100)
    assert len(sent) == 3


def test_full_recovery_does_not_reset_coverage_interval(health_watchdog):
    runtime, clock, sent, check = health_watchdog
    check(problems=["Slickdeals: partial coverage"])
    clock[0] += 60
    assert not check()["problems"]
    clock[0] += 60
    check(problems=["Slickdeals: partial coverage"])
    assert len(sent) == 1
    assert json.loads((runtime / "watchdog-receipt.json").read_text())["ntfy"]["sent_at"] == 10_000
    clock[0] = 10_000 + monitor.HEALTH_CHANGE_SECONDS
    check(problems=["Slickdeals: partial coverage"])
    assert len(sent) == 2


def test_legacy_receipt_migration_does_not_repeat_delivered_warning(health_watchdog):
    runtime, clock, sent, check = health_watchdog
    prior = ["hp-example: Network request failed"]
    fingerprint = hashlib.sha256(json.dumps(sorted(prior)).encode()).hexdigest()
    (runtime / "watchdog.json").write_text(json.dumps({"problems": prior}))
    (runtime / "watchdog-receipt.json").write_text(json.dumps(
        {"ntfy": fingerprint, "fingerprint": fingerprint, "sent_at": clock[0] - 60}))
    check(jobs={"hp-example": failed_job("Host is backing off")})
    assert not sent
    receipt = json.loads((runtime / "watchdog-receipt.json").read_text())["ntfy"]
    assert receipt["problem_keys"] == ["job:hp-example"]
    assert receipt["sent_at"] == clock[0] - 60
    clock[0] += 60
    check(jobs={"hp-example": failed_job()}, heartbeat=clock[0] - 100)
    assert len(sent) == 1
    assert sent[0].buys[0].priority == 4


def test_each_transport_retries_and_tracks_its_own_delivery_interval(health_watchdog, monkeypatch):
    _, clock, ntfy, check = health_watchdog
    discord = []

    def fail(_):
        raise RuntimeError("offline")

    monkeypatch.setattr(monitor, "channels", lambda **_: (
        Channel("ntfy", "push", ntfy.append), Channel("discord", "push", fail)))
    with pytest.raises(RuntimeError):
        check(problems=["Coverage degraded"])
    clock[0] += 60
    monkeypatch.setattr(monitor, "channels", lambda **_: (
        Channel("ntfy", "push", ntfy.append), Channel("discord", "push", discord.append)))
    check(problems=["Coverage degraded"])
    assert len(ntfy) == len(discord) == 1
    clock[0] = 10_000 + monitor.HEALTH_CHANGE_SECONDS
    check(problems=["Coverage degraded", "Additional coverage gap"])
    assert len(ntfy) == 2
    assert len(discord) == 1
    clock[0] += 60
    check(problems=["Coverage degraded", "Additional coverage gap"])
    assert len(ntfy) == len(discord) == 2


def test_offline_transport_cannot_mask_recovery_and_a_new_stale_heartbeat(health_watchdog, monkeypatch):
    _, clock, ntfy, check = health_watchdog

    def fail(_):
        raise RuntimeError("offline")

    monkeypatch.setattr(monitor, "channels", lambda **_: (
        Channel("ntfy", "push", ntfy.append), Channel("discord", "push", fail)))
    jobs = {"hp-example": failed_job()}
    for heartbeat_stale in (False, True, False, True):
        clock[0] += 60
        with pytest.raises(RuntimeError):
            check(jobs=jobs, heartbeat=clock[0] - 100 if heartbeat_stale else None)
    assert len(ntfy) == 3
    assert ntfy[-1].buys[0].badge == "MONITOR STALE"
