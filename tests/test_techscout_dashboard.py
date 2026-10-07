import json
import threading
from datetime import datetime, timezone

import pytest
import requests

from alerters.techscout.dashboard import Dashboard, FRESH_SECONDS, create_server, snapshot

NOW = datetime(2026, 10, 7, 2, tzinfo=timezone.utc).timestamp()


def product(item_id="1", **changes):
    return {"item_id": item_id, "title": "Gaming PC RTX 5080 9800X3D 32GB DDR5 1TB SSD",
            "seller": "Walmart.com", "condition": "New", "price": 2000, "shipping": 0,
            "available": True, "memory_fit": {"eligible": True, "installed_gb": 32, "potential_gb": 96,
                "status": "NEEDS SPECS", "summary": "Four slots and module layout unverified"},
            "comparison_key": ["desktop", "RTX 5080", "9800X3D", "32GB DDR5 RAM", "1000GB SSD", "new"],
            "warnings": [], "queries": ["RTX 5080 gaming desktop"], **changes}


def save(directory, rows=None, *, category="desktop-memory", at=NOW, **changes):
    data = {"category": category, "observed_at": datetime.fromtimestamp(at, timezone.utc).isoformat(),
            "zip_code": "94105", "products": rows if rows is not None else [product()],
            "problems": [], "queries": ["RTX 5080 gaming desktop"], "coverage": [], **changes}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"latest-{category}.json").write_text(json.dumps(data), encoding="utf-8")


def test_rank_known_delivered_totals_within_gpu_ram_groups(tmp_path):
    save(tmp_path, [product("1", price=2000, shipping=200), product("2", price=2100, shipping=0),
                   product("3", title="Gaming PC RTX 5090 32GB DDR5", price=3000),
                   product("4", memory_fit={"eligible": True, "installed_gb": 64, "status": "NEEDS SPECS"})])
    result = snapshot(tmp_path, "desktop-memory", now=NOW)
    assert len(result["groups"]) == 3
    rows = result["groups"][0]["rows"]
    assert [r["id"] for r in rows] == ["2", "1"]
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[1]["total"] == 2200


def test_all_deals_includes_latest_unique_walmart_rows_and_failure_status(tmp_path):
    save(tmp_path, [product("1", price=2000)], at=NOW-60)
    save(tmp_path, [product("1", price=1900), product("2")], category="computers", at=NOW)
    result = snapshot(tmp_path, "monitor", now=NOW, failed_checks={"computers": NOW+1})
    rows = [r for g in result["groups"] for r in g["rows"]] + result["held"]
    assert len(rows) == 2
    assert next(r for r in rows if r["id"] == "1")["price"] == 1900
    assert all(r["verification_reasons"] == ["Last check failed"] for r in rows)
    assert result["sources"][0]["source"] == "walmart"
    assert result["sources"][0]["count"] == 2


def test_watch_endpoint_requires_origin_and_rejects_invalid_payload(web):
    session, base, app, calls = web
    assert session.get(base + "/workspace.js").status_code == 200
    assert session.get(base + "/api/workspace").json()["supported"] is False
    assert session.post(base + "/api/watches", json={}).status_code == 403
    headers = {"Origin": base, "X-TechScout-Token": app.token}
    assert session.post(base + "/api/watches", json={"settings": "bad"}, headers=headers).status_code == 400
    assert not calls


def test_documented_layout_ranks_before_unverified_not_claiming_compatibility(tmp_path):
    fit = {"eligible": True, "installed_gb": 32, "status": "POSSIBLE REUSE", "summary": "Mixed-kit stability unverified"}
    save(tmp_path, [product("1", price=1000), product("2", price=2200, memory_fit=fit)])
    rows = snapshot(tmp_path,"desktop-memory",now=NOW)["groups"][0]["rows"]
    assert rows[0]["id"] == "2" and "unverified" in rows[0]["fit_summary"]


def test_independent_facets_span_ranked_groups_and_held_offers(tmp_path):
    save(tmp_path, [
        product("1", title="Desktop RTX 5090 32GB DDR5 1TB SSD"),
        product("2", title="Desktop RTX 5090 64GB DDR5 2TB SSD", condition="Used",
                memory_fit={"eligible": True, "installed_gb": 64, "status": "NEEDS SPECS"}),
        product("3", title="Desktop RTX 5090 32GB DDR5 1TB SSD", shipping=None),
        product("4"),
    ])
    result = snapshot(tmp_path, "desktop-memory", now=NOW)
    rows = [row for group in result["groups"] for row in group["rows"]] + result["held"]
    matching = [row for row in rows if row["facets"]["gpu"] == "RTX 5090"]
    assert {row["id"] for row in matching} == {"1", "2", "3"}
    assert {row["facets"]["ram"] for row in matching} == {"32GB", "64GB"}
    assert {row["facets"]["condition"] for row in matching} == {"New", "Used"}
    assert {row["id"] for row in result["held"]} == {"3"}


def test_build_preferences_are_separate_from_availability_failures(tmp_path):
    save(tmp_path, [product(title="Desktop RTX 5090 96GB RAM 6TB SSD",
                           memory_fit={"eligible": False, "status": "OUTSIDE REUSE WATCH", "summary": "Outside reuse plan"})])
    row = snapshot(tmp_path, "desktop-memory", now=NOW)["held"][0]
    assert row["verification_reasons"] == []
    assert row["preference_reasons"] == ["Outside reuse plan"]
    assert row["facets"]["ram"] == "96GB"
    failed = snapshot(tmp_path, "desktop-memory", now=NOW, failed_at=NOW)["held"][0]
    assert failed["verification_reasons"] == ["Last check failed"]
    assert failed["preference_reasons"] == ["Outside reuse plan"]


def test_walmart_source_status_distinguishes_stale_missing_and_failure(tmp_path):
    assert snapshot(tmp_path,"desktop-memory",now=NOW)["sources"][0]["status"] == "Not checked yet"
    save(tmp_path,at=NOW-1800)
    assert snapshot(tmp_path,"desktop-memory",now=NOW)["sources"][0]["status"] == "Manual check overdue"
    assert snapshot(tmp_path,"desktop-memory",now=NOW,failed_at=NOW)["sources"][0]["status"] == "Last check failed"


def test_cpu_display_reparses_old_truncated_comparison_keys(tmp_path):
    save(tmp_path,[product(title="Gaming PC RTX 5080 Ultra 5 250KF Plus 32GB DDR5 1TB SSD")])
    row = snapshot(tmp_path,"desktop-memory",now=NOW)["groups"][0]["rows"][0]
    assert row["cpu"] == "ULTRA 5 250KF PLUS"


@pytest.mark.parametrize("changes,reason", [
    ({"shipping": None}, "Shipping unknown"), ({"price": 0}, "Price unknown"),
    ({"price": float("nan")}, "Price unknown"), ({"shipping": -1}, "Shipping unknown"),
    ({"available": False}, "Unavailable"), ({"available": "true"}, "Unavailable"),
    ({"seller": "Not published"}, "Seller"), ({"condition": ""}, "condition"),
    ({"memory_fit": None}, "configuration"),
    ({"memory_fit": {"eligible": False, "summary": "No reuse path"}}, "No reuse path"),
])
def test_incomplete_or_unavailable_offers_are_held(tmp_path, changes, reason):
    save(tmp_path, [product(**changes)])
    result = snapshot(tmp_path,"desktop-memory",now=NOW)
    assert not result["groups"] and any(reason in r for r in result["held"][0]["reasons"])


@pytest.mark.parametrize("at", [NOW - FRESH_SECONDS - 1, NOW + 60])
def test_stale_or_future_data_cannot_rank(tmp_path, at):
    save(tmp_path, at=at)
    result = snapshot(tmp_path,"desktop-memory",now=NOW)
    assert not result["fresh"] and not result["groups"] and len(result["held"]) == 1


def test_failed_attempt_invalidates_recent_snapshot(tmp_path):
    save(tmp_path, at=NOW - 60)
    result = snapshot(tmp_path,"desktop-memory",now=NOW,failed_at=NOW - 30)
    assert not result["fresh"] and "Last check failed" in result["held"][0]["reasons"]


def test_malformed_and_missing_reports_do_not_look_successful(tmp_path):
    assert snapshot(tmp_path,"tablets",now=NOW)["problems"]
    (tmp_path / "latest-tablets.json").write_text("[]")
    assert snapshot(tmp_path,"tablets",now=NOW)["problems"]
    save(tmp_path, observed_at="invalid")
    assert not snapshot(tmp_path,"desktop-memory",now=NOW)["groups"]


def test_no_path_injection_or_api_urls(tmp_path):
    with pytest.raises(ValueError):
        snapshot(tmp_path,"../../credentials",now=NOW)
    save(tmp_path,[product(url="javascript:bad()",private_key="SECRET"), product(), product("../private")])
    result = snapshot(tmp_path,"desktop-memory",now=NOW)
    encoded = json.dumps(result)
    assert len(result["groups"][0]["rows"]) == 1
    assert "javascript:" not in encoded and "SECRET" not in encoded
    assert result["groups"][0]["rows"][0]["url"] == "https://www.walmart.com/ip/1"


def test_tablet_variant_mismatch_is_held(tmp_path):
    save(tmp_path,[product(title="iPad Air 128GB", queries=["iPad Air 256GB"])], category="tablets")
    result = snapshot(tmp_path,"tablets",now=NOW)
    assert not result["groups"] and "Storage variant" in result["held"][0]["reasons"][0]


def test_non_desktop_prices_are_not_performance_rankings(tmp_path):
    save(tmp_path,[product(title="Tablet 128GB", memory_fit=None)], category="tablets")
    row = snapshot(tmp_path,"tablets",now=NOW)["groups"][0]["rows"][0]
    assert "not equivalent" in row["why"]


def test_receipts_survive_restart_without_exposing_extra_fields(tmp_path):
    save(tmp_path,at=NOW-60)
    receipt = {"desktop-memory":{"status":"checking","at":NOW-30,"token":"SECRET"}}
    (tmp_path / "dashboard-last-check.json").write_text(json.dumps(receipt))
    app = Dashboard(tmp_path,lambda _:0,clock=lambda:NOW)
    state = app.state("desktop-memory")
    assert not state["snapshot"]["fresh"] and "SECRET" not in json.dumps(state)


def test_refresh_serialization_and_cooldown(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def refresh(category):
        entered.set()
        release.wait(2)
        return 0
    app = Dashboard(tmp_path,refresh,clock=lambda:NOW)
    try:
        assert app.start("desktop-memory")[0] == 202
        assert entered.wait(1)
        assert app.start("tablets")[0] == 409
        assert app.state("desktop-memory")["running"] == "desktop-memory"
    finally:
        release.set()


def test_failure_receipt_and_cooldown(tmp_path):
    save(tmp_path,at=NOW-1)
    app = Dashboard(tmp_path,lambda _:2,clock=lambda:NOW)
    app.last_start = NOW
    app._run("desktop-memory")
    assert app.state("desktop-memory")["last_check"]["status"] == "failed"
    assert not app.state("desktop-memory")["snapshot"]["fresh"]
    assert app.start("desktop-memory")[0] == 429


@pytest.fixture
def web(tmp_path):
    save(tmp_path)
    calls = []
    app = Dashboard(tmp_path,lambda category: calls.append(category) or 0,clock=lambda:NOW)
    server = create_server(app,0)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    base = f"http://127.0.0.1:{server.server_port}"
    yield session,base,app,calls
    server.shutdown()
    server.server_close()
    session.close()
    thread.join(2)


def test_gets_cannot_start_research_and_no_files_are_served(web):
    session,base,app,calls = web
    assert session.get(base + "/").status_code == 200
    assert session.get(base + "/dashboard.js").status_code == 200
    assert session.get(base + "/browsing.js").status_code == 200
    response = session.get(base + "/api/state")
    assert response.status_code == 200 and response.json()["snapshot"]["fresh"]
    assert app.token not in response.text
    for path in ("/api/refresh", "/settings.json", "/../credentials/application.json"):
        assert session.get(base + path).status_code == 404
    assert not calls
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("headers", [{}, {"Origin":"https://evil.example"}, {"Host":"evil.example"}])
def test_refresh_rejects_cross_origin_or_missing_token(web, headers):
    session,base,app,calls = web
    assert session.post(base + "/api/refresh",json={"category":"desktop-memory"},headers=headers).status_code == 403
    assert not calls


def test_rebinding_host_cannot_read_snapshot(web):
    session,base,app,calls = web
    assert session.get(base + "/api/state",headers={"Host":"evil.example"}).status_code == 403


def test_local_page_authorized_refresh_and_input_bounds(web):
    session,base,app,calls = web
    headers = {"Origin":base,"X-TechScout-Token":app.token}
    for payload in ({"category":"../settings"}, {"category":[]}, {"category":"tablets","settings":"secret"}):
        assert session.post(base + "/api/refresh",json=payload,headers=headers).status_code == 400
    assert not calls
    response = session.post(base + "/api/refresh",json={"category":"desktop-memory"},headers=headers)
    assert response.status_code == 202


def test_dashboard_cli_start_does_not_load_credentials(tmp_path, monkeypatch):
    from alerters.techscout import __main__ as cli, dashboard
    called = []
    def fake_serve(directory, callback, port, **kwargs):
        called.append((directory, port))
    def forbidden(*args):
        raise AssertionError("Dashboard startup must not load API credentials")
    monkeypatch.setattr(dashboard, "serve", fake_serve)
    monkeypatch.setattr(cli.Credentials, "load", forbidden)
    assert cli.main(["--serve", "--output", str(tmp_path), "--settings", str(tmp_path / "missing.json")]) == 0
    assert called == [(tmp_path,8768)]


def test_dashboard_port_cannot_be_claimed_by_second_instance(tmp_path):
    app = Dashboard(tmp_path, lambda _: 0)
    server = create_server(app, 0)
    try:
        with pytest.raises(OSError):
            duplicate = create_server(app, server.server_port)
            duplicate.server_close()
    finally:
        server.server_close()
