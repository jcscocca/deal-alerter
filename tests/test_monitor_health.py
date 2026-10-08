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


def failed_job(error="Network request failed", *, kind="hp", at=10_000):
    return {"kind": kind, "interval": 120, "last_success": 0, "error": error, "last_error_at": at}


def mature(clock, check, **status):
    check(**status)
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    return check(**status)


def test_new_discoveries_get_their_own_initial_check_window():
    job = {**failed_job(""), "created_at": 10_000}
    status = {"started": 1_000, "heartbeat": 10_600, "jobs": {"new": job}}
    assert monitor.health_problems(status, 10_600) == []
    assert monitor.health_problems(status, 10_601) == ["new: no successful check"]
    job["error"] = "Network request failed"
    status["heartbeat"] = 10_001
    assert monitor.health_problems(status, 10_001) == ["new: Network request failed"]
    # Old schedules without a creation timestamp retain their original fallback.
    del job["created_at"]
    assert monitor.health_problems(status, 10_001) == ["new: no successful check"]


def test_error_wording_and_stale_transition_do_not_repeat_an_outage(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    check(jobs=jobs)
    assert not sent
    clock[0] += 60
    jobs["hp-example"]["error"] = "Host is backing off"
    assert "backing off" in check(jobs=jobs)["problems"][0]
    clock[0] = 10_000 + monitor.HEALTH_GRACE_SECONDS - 1
    check(jobs=jobs)
    assert not sent
    clock[0] += 2
    assert "no successful check" in check(jobs=jobs)["problems"][0]
    assert len(sent) == 1
    assert sent[0].buys[0].priority == 2
    assert sent[0].buys[0].badge == "COVERAGE DEGRADED"
    assert "Monitor running" in sent[0].buys[0].headline
    assert sent[0].buys[0].reason == "HP: 1 connection/backoff check"
    assert "hp-example" not in sent[0].buys[0].reason


def test_staggered_product_failures_are_batched_and_unchanged_warnings_remind_daily(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    mature(clock, check, jobs=jobs)
    for minute in range(1, 13):
        clock[0] = 10_600 + minute * 60
        jobs[f"newegg-{minute}"] = failed_job(kind="newegg")
        check(jobs=jobs)
    assert len(sent) == 1
    clock[0] = 10_600 + monitor.HEALTH_CHANGE_SECONDS - 1
    check(jobs=jobs)
    assert len(sent) == 1
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 2
    assert sent[-1].buys[0].reason == "Newegg: 12 connection/backoff checks"
    assert "HP" not in sent[-1].buys[0].reason
    last_sent = clock[0]
    clock[0] = last_sent + monitor.HEALTH_REMINDER_SECONDS - 1
    check(jobs=jobs)
    assert len(sent) == 2
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 3
    assert "HP" in sent[-1].buys[0].reason and "Newegg" in sent[-1].buys[0].reason


def test_lost_heartbeat_bypasses_coverage_interval_and_can_alert_after_partial_recovery(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp-example": failed_job()}
    mature(clock, check, jobs=jobs)
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
    mature(clock, check, problems=["Unexpected collector failure"])
    clock[0] += 60
    assert not check()["problems"]
    clock[0] += 60
    check(problems=["Unexpected collector failure"])
    assert len(sent) == 1
    assert json.loads((runtime / "watchdog-receipt.json").read_text())["ntfy"]["sent_at"] == 10_600
    clock[0] = 10_600 + monitor.HEALTH_CHANGE_SECONDS
    check(problems=["Unexpected collector failure"])
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
    assert receipt["problem_keys"] == ["source:hp"]
    assert receipt["sent_at"] == clock[0] - 60
    clock[0] += 60
    check(jobs={"hp-example": failed_job()}, heartbeat=clock[0] - 100)
    assert len(sent) == 1
    assert sent[0].buys[0].priority == 4


def test_v2_job_receipts_migrate_without_replaying_coverage_alert(health_watchdog):
    runtime, clock, sent, check = health_watchdog
    (runtime / "watchdog-receipt.json").write_text(json.dumps({
        "version": 2, "ntfy": {"problem_keys": ["job:hp-product", "job:hp-discovery"], "sent_at": 9_999}}))
    jobs = {"hp-product": failed_job(), "hp-discovery": failed_job(kind="discover-hp")}
    mature(clock, check, jobs=jobs)
    assert not sent
    assert json.loads((runtime / "watchdog-receipt.json").read_text())["ntfy"] == {
        "problem_keys": ["source:hp"], "sent_at": 9_999}


def test_listing_uncertainty_and_known_coverage_limits_never_push(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {f"skytech-{i}": failed_job(monitor.LISTING_UNVERIFIED, kind="skytech") for i in range(19)}
    jobs["reddit"] = failed_job("Path disallowed by robots.txt", kind="reddit")
    result = mature(clock, check, jobs=jobs, problems=[monitor.SLICKDEALS_COVERAGE])
    assert len(result["problems"]) == 21
    assert result["incidents"] == {} and result["alertable"] == [] and not sent
    clock[0] += monitor.HEALTH_REMINDER_SECONDS
    check(jobs=jobs, problems=[monitor.SLICKDEALS_COVERAGE])
    assert not sent


def test_recovered_retailer_drops_old_connection_errors_awaiting_retry(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {f"newegg-{i}": failed_job(kind="newegg") for i in range(31)}
    check(jobs=jobs)
    clock[0] += 240
    jobs["newegg-0"].update(error="", last_success=clock[0], last_fetch_success=clock[0])
    assert check(jobs=jobs)["incidents"] == {}
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    assert check(jobs=jobs)["incidents"] == {} and not sent
    # A later failure starts a new grace period; the earlier success cannot hide it.
    jobs["newegg-1"].update(last_error_at=clock[0])
    check(jobs=jobs)
    assert not sent
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    check(jobs=jobs)
    assert len(sent) == 1 and "Newegg: 1 connection" in sent[0].buys[0].reason


def test_short_outage_recovery_and_retry_reset_the_grace_period(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"hp": failed_job()}
    check(jobs=jobs)
    clock[0] += 599
    assert check()["incidents"] == {}
    clock[0] += 1
    check(jobs=jobs)
    assert not sent
    clock[0] += 599
    check(jobs=jobs)
    assert not sent
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 1


def test_successful_requests_do_not_hide_parser_or_delivery_failures(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"newegg-good": failed_job("", kind="newegg"),
            "newegg-bad": failed_job("Selected product schema changed", kind="newegg")}
    jobs["newegg-good"].update(last_success=10_001)
    mature(clock, check, jobs=jobs)
    assert len(sent) == 1 and "failed or overdue" in sent[0].buys[0].reason


def test_unmatured_incident_is_not_marked_delivered_with_another_alert(health_watchdog):
    runtime, clock, sent, check = health_watchdog
    jobs = {"hp": failed_job()}
    check(jobs=jobs)
    clock[0] += 599
    jobs["newegg"] = failed_job(kind="newegg")
    check(jobs=jobs)
    clock[0] += 1
    check(jobs=jobs)
    assert len(sent) == 1 and "Newegg" not in sent[0].buys[0].reason
    assert json.loads((runtime / "watchdog-receipt.json").read_text())["ntfy"]["problem_keys"] == ["source:hp"]
    clock[0] += monitor.HEALTH_CHANGE_SECONDS
    check(jobs=jobs)
    assert len(sent) == 2 and "Newegg" in sent[1].buys[0].reason


@pytest.mark.parametrize("error", ["Host is backing off", monitor.LISTING_UNVERIFIED,
                                  "Path disallowed by robots.txt"])
def test_old_notes_or_recovered_connections_do_not_hide_overdue_jobs(health_watchdog, error):
    _, clock, sent, check = health_watchdog
    jobs = {"newegg-good": {**failed_job("", kind="newegg"), "last_success": clock[0]},
            "newegg-missed": {**failed_job(error, kind="newegg", at=8_000), "next": 8_500}}
    mature(clock, check, jobs=jobs)
    assert len(sent) == 1
    assert sent[0].buys[0].reason == "Newegg: 1 failed or overdue check"


def test_legacy_sources_keep_separate_identities_and_grace(health_watchdog):
    _, clock, sent, check = health_watchdog
    jobs = {"legacy-one": {**failed_job(kind="legacy"), "source": "ebay"},
            "legacy-two": {**failed_job(kind="legacy"), "source": "apple-refurb"}}
    mature(clock, check, jobs=jobs)
    assert len(sent) == 1
    assert "eBay" in sent[0].buys[0].reason and "Apple refurbished" in sent[0].buys[0].reason


def test_each_transport_retries_and_tracks_its_own_delivery_interval(health_watchdog, monkeypatch):
    _, clock, ntfy, check = health_watchdog
    discord = []

    def fail(_):
        raise RuntimeError("offline")

    monkeypatch.setattr(monitor, "channels", lambda **_: (
        Channel("ntfy", "push", ntfy.append), Channel("discord", "push", fail)))
    check(problems=["Coverage degraded"])
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    with pytest.raises(RuntimeError):
        check(problems=["Coverage degraded"])
    clock[0] += 60
    monkeypatch.setattr(monitor, "channels", lambda **_: (
        Channel("ntfy", "push", ntfy.append), Channel("discord", "push", discord.append)))
    check(problems=["Coverage degraded"])
    assert len(ntfy) == len(discord) == 1
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    check(problems=["Coverage degraded", "Additional coverage gap"])
    assert len(ntfy) == len(discord) == 1
    clock[0] = 10_600 + monitor.HEALTH_CHANGE_SECONDS
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
    # Mature the ordinary failure before exercising heartbeat recovery.
    check(jobs=jobs)
    clock[0] += monitor.HEALTH_GRACE_SECONDS
    for heartbeat_stale in (False, True, False, True):
        clock[0] += 60
        with pytest.raises(RuntimeError):
            check(jobs=jobs, heartbeat=clock[0] - 100 if heartbeat_stale else None)
    assert len(ntfy) == 3
    assert ntfy[-1].buys[0].badge == "MONITOR STALE"
