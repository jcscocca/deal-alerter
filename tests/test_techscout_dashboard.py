import json
import threading
from datetime import datetime, timezone

import pytest
import requests

from alerters.techscout.dashboard import Dashboard, FRESH_SECONDS, create_server, snapshot

NOW = datetime(2026, 10, 7, 2, tzinfo=timezone.utc).timestamp()


def product(item_id="1", **changes):
    return {"item_id": item_id, "title": "NVIDIA GeForce RTX 5080 16GB GDDR7 graphics card",
            "seller": "Walmart.com", "condition": "New", "price": 900, "shipping": 0,
            "available": True, "stock": "Available", "warnings": [],
            "queries": ["NVIDIA GeForce graphics card"], **changes}


def save(directory, rows=None, *, category="parts", at=NOW, **changes):
    data = {"category": category, "observed_at": datetime.fromtimestamp(at, timezone.utc).isoformat(),
            "zip_code": "94105", "products": rows if rows is not None else [product()],
            "problems": [], "queries": ["NVIDIA GeForce graphics card"], "coverage": [], **changes}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"latest-{category}.json").write_text(json.dumps(data), encoding="utf-8")


def test_rank_known_delivered_totals_within_product_condition_groups(tmp_path):
    save(tmp_path, [product("1", price=900, shipping=100), product("2", price=950),
                   product("3", condition="Used", price=700)])
    result = snapshot(tmp_path, "parts", now=NOW)
    assert len(result["groups"]) == 2
    rows = next(g["rows"] for g in result["groups"] if "New" in g["name"])
    assert [r["id"] for r in rows] == ["2", "1"]
    assert [r["rank"] for r in rows] == [1, 2]
    assert rows[1]["total"] == 1000


def test_all_deals_includes_latest_unique_walmart_rows_and_failure_status(tmp_path):
    title = "Corsair 64GB DDR5 desktop memory kit"
    save(tmp_path, [product("1", title=title, price=200)], at=NOW-60)
    save(tmp_path, [product("1", title=title, price=190), product("2", title=title)], category="memory", at=NOW)
    result = snapshot(tmp_path, "monitor", now=NOW, failed_checks={"memory": NOW+1})
    rows = [r for g in result["groups"] for r in g["rows"]] + result["held"]
    assert len(rows) == 2
    assert next(r for r in rows if r["id"] == "1")["price"] == 190
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


def test_obsolete_ram_completion_evidence_does_not_affect_parts_order(tmp_path):
    save(tmp_path, [product("1", price=800, memory_fit={"eligible": False, "summary": "No reuse"}),
                    product("2", price=900, memory_fit={"eligible": True, "status": "POSSIBLE REUSE"})])
    rows = snapshot(tmp_path, "parts", now=NOW)["groups"][0]["rows"]
    assert [r["id"] for r in rows] == ["1", "2"]
    assert not any(key in rows[0] for key in ("potential", "fit_summary", "prebuilt_value"))


def test_independent_facets_span_ranked_groups_and_held_offers(tmp_path):
    save(tmp_path, [
        product("1", title="RTX 5090 32GB GDDR7 graphics card"),
        product("2", title="RTX 5090 32GB GDDR7 graphics card", condition="Used"),
        product("3", title="RTX 5090 32GB GDDR7 graphics card", shipping=None),
        product("4"),
    ])
    result = snapshot(tmp_path, "parts", now=NOW)
    rows = [row for group in result["groups"] for row in group["rows"]] + result["held"]
    matching = [row for row in rows if row["facets"]["gpu"] == "RTX 5090"]
    assert {row["id"] for row in matching} == {"1", "2", "3"}
    assert {row["facets"]["ram"] for row in matching} == {"Not established"}
    assert {row["facets"]["condition"] for row in matching} == {"New", "Used"}
    assert {row["id"] for row in result["held"]} == {"3"}


def test_memory_products_have_no_completed_build_gate(tmp_path):
    save(tmp_path, [product(title="Corsair DDR5 96GB (2x48GB) UDIMM desktop RAM", memory_fit={"eligible": False})])
    row = snapshot(tmp_path, "parts", now=NOW)["groups"][0]["rows"][0]
    assert row["verification_reasons"] == []
    assert "preference_reasons" not in row
    assert row["facets"]["ram"] == "96GB"
    failed = snapshot(tmp_path, "parts", now=NOW, failed_at=NOW)["held"][0]
    assert failed["verification_reasons"] == ["Last check failed"]


def test_walmart_source_status_distinguishes_stale_missing_and_failure(tmp_path):
    assert snapshot(tmp_path,"parts",now=NOW)["sources"][0]["status"] == "Not checked yet"
    save(tmp_path,at=NOW-1800)
    assert snapshot(tmp_path,"parts",now=NOW)["sources"][0]["status"] == "Manual check overdue"
    assert snapshot(tmp_path,"parts",now=NOW,failed_at=NOW)["sources"][0]["status"] == "Last check failed"


def test_walmart_sold_out_quote_keeps_stock_and_original_check_time(tmp_path):
    save(tmp_path, [product(stock="Not available", available=False, price=4828.81)], at=NOW-86400)
    result = snapshot(tmp_path, "monitor", now=NOW)
    row = result["held"][0]
    assert not result["groups"] and row["stock"] == "out_of_stock"
    assert row["checked_at"] == datetime.fromtimestamp(NOW-86400, timezone.utc).isoformat()
    assert "Out of stock at last check" in row["verification_reasons"]
    assert row["price"] == 4828.81


@pytest.mark.parametrize("stock,expected", [(None, "unknown"), ("Not published", "unknown"),
                                           ("Not available", "out_of_stock"), ("Pre-order", "preorder")])
def test_walmart_unknown_stock_is_not_invented_as_sold_out(tmp_path, stock, expected):
    save(tmp_path, [product(stock=stock, available=False)])
    row = snapshot(tmp_path, "parts", now=NOW)["held"][0]
    assert row["stock"] == expected and not row["available"]


def test_explicit_walmart_sold_out_wins_over_conflicting_available_flag(tmp_path):
    save(tmp_path, [product(stock="Not available", available=True)])
    result = snapshot(tmp_path, "parts", now=NOW)
    assert not result["groups"] and not result["held"][0]["available"]


def test_cpu_display_reparses_old_truncated_comparison_keys(tmp_path):
    save(tmp_path,[product(title="Intel Core Ultra 5 250KF Plus desktop processor")])
    row = snapshot(tmp_path,"parts",now=NOW)["groups"][0]["rows"][0]
    assert row["cpu"] == "ULTRA 5 250KF PLUS"


@pytest.mark.parametrize("changes,reason", [
    ({"shipping": None}, "Shipping unknown"), ({"price": 0}, "Price unknown"),
    ({"price": float("nan")}, "Price unknown"), ({"shipping": -1}, "Shipping unknown"),
    ({"available": False}, "Unavailable"), ({"available": "true"}, "Unavailable"),
    ({"seller": "Not published"}, "Seller"), ({"condition": ""}, "condition"),
])
def test_incomplete_or_unavailable_offers_are_held(tmp_path, changes, reason):
    save(tmp_path, [product(**changes)])
    result = snapshot(tmp_path,"parts",now=NOW)
    assert not result["groups"] and any(reason in r for r in result["held"][0]["reasons"])


@pytest.mark.parametrize("at", [NOW - FRESH_SECONDS - 1, NOW + 60])
def test_stale_or_future_data_cannot_rank(tmp_path, at):
    save(tmp_path, at=at)
    result = snapshot(tmp_path,"parts",now=NOW)
    assert not result["fresh"] and not result["groups"] and len(result["held"]) == 1


def test_failed_attempt_invalidates_recent_snapshot(tmp_path):
    save(tmp_path, at=NOW - 60)
    result = snapshot(tmp_path,"parts",now=NOW,failed_at=NOW - 30)
    assert not result["fresh"] and "Last check failed" in result["held"][0]["reasons"]


def test_malformed_and_missing_reports_do_not_look_successful(tmp_path):
    assert snapshot(tmp_path,"monitors",now=NOW)["problems"]
    (tmp_path / "latest-monitors.json").write_text("[]")
    assert snapshot(tmp_path,"monitors",now=NOW)["problems"]
    save(tmp_path, observed_at="invalid")
    assert not snapshot(tmp_path,"parts",now=NOW)["groups"]


def test_no_path_injection_or_api_urls(tmp_path):
    with pytest.raises(ValueError):
        snapshot(tmp_path,"../../credentials",now=NOW)
    save(tmp_path,[product(url="javascript:bad()",private_key="SECRET"), product(), product("../private")])
    result = snapshot(tmp_path,"parts",now=NOW)
    encoded = json.dumps(result)
    assert len(result["groups"][0]["rows"]) == 1
    assert "javascript:" not in encoded and "SECRET" not in encoded
    assert result["groups"][0]["rows"][0]["url"] == "https://www.walmart.com/ip/1"


def test_whole_computers_cannot_leak_into_parts_or_saved_all_deals(tmp_path):
    save(tmp_path, [product(title="Gaming PC RTX 5090 96GB DDR5 2TB SSD"), product("2")])
    assert snapshot(tmp_path, "parts", now=NOW)["count"] == 1
    assert snapshot(tmp_path, "monitor", now=NOW)["count"] == 1
    assert snapshot(tmp_path, "parts", now=NOW)["groups"][0]["rows"][0]["id"] == "2"


def test_unrated_prices_are_not_performance_or_deal_rankings(tmp_path):
    save(tmp_path, [product(title="Samsung 990 Pro 2TB NVMe SSD")])
    row = snapshot(tmp_path, "parts", now=NOW)["groups"][0]["rows"][0]
    assert "unlike models" in row["why"] or "alone does not establish value" in row["why"]
    assert not row.get("judgment")


def test_retired_categories_and_saved_desktop_reports_are_inactive(tmp_path):
    save(tmp_path, [product(title="Gaming PC RTX 5090 96GB DDR5 2TB SSD")], category="desktop-memory")
    assert snapshot(tmp_path, "monitor", now=NOW)["count"] == 0
    for category in ("desktop-memory", "computers", "tablets"):
        with pytest.raises(ValueError):
            snapshot(tmp_path, category, now=NOW)
        assert Dashboard(tmp_path, lambda _: 0).start(category)[0] == 400


def test_receipts_survive_restart_without_exposing_extra_fields(tmp_path):
    save(tmp_path,at=NOW-60)
    receipt = {"parts":{"status":"checking","at":NOW-30,"token":"SECRET"}}
    (tmp_path / "dashboard-last-check.json").write_text(json.dumps(receipt))
    app = Dashboard(tmp_path,lambda _:0,clock=lambda:NOW)
    state = app.state("parts")
    assert not state["snapshot"]["fresh"] and "SECRET" not in json.dumps(state)


def test_refresh_serialization_and_cooldown(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def refresh(category):
        entered.set()
        release.wait(2)
        return 0
    app = Dashboard(tmp_path,refresh,clock=lambda:NOW)
    try:
        assert app.start("parts")[0] == 202
        assert entered.wait(1)
        assert app.start("monitors")[0] == 409
        assert app.state("parts")["running"] == "parts"
    finally:
        release.set()


def test_failure_receipt_and_cooldown(tmp_path):
    save(tmp_path,at=NOW-1)
    app = Dashboard(tmp_path,lambda _:2,clock=lambda:NOW)
    app.last_start = NOW
    app._run("parts")
    assert app.state("parts")["last_check"]["status"] == "failed"
    assert not app.state("parts")["snapshot"]["fresh"]
    assert app.start("parts")[0] == 429


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
    assert session.post(base + "/api/refresh",json={"category":"parts"},headers=headers).status_code == 403
    assert not calls


def test_rebinding_host_cannot_read_snapshot(web):
    session,base,app,calls = web
    assert session.get(base + "/api/state",headers={"Host":"evil.example"}).status_code == 403


def test_local_page_authorized_refresh_and_input_bounds(web):
    session,base,app,calls = web
    headers = {"Origin":base,"X-TechScout-Token":app.token}
    for payload in ({"category":"../settings"}, {"category":[]}, {"category":"monitors","settings":"secret"}):
        assert session.post(base + "/api/refresh",json=payload,headers=headers).status_code == 400
    assert not calls
    response = session.post(base + "/api/refresh",json={"category":"parts"},headers=headers)
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


def test_health_reports_loaded_build_and_process_instance(web, monkeypatch):
    session, base, app, _ = web
    loaded = session.get(base + "/health").json()
    assert loaded["service"] == "TechScout" and loaded["status"] == "ok"
    assert loaded["version"].startswith("standout-v3-") and loaded["watch_schema_version"] == 3
    assert loaded["instance_id"] == app.instance_id and loaded["pid"] > 0
    # Changing disk code must not make an old process claim it loaded that code.
    monkeypatch.setattr("alerters.techscout.dashboard.app_version", lambda: "next-build")
    assert session.get(base + "/health").json() == loaded
    restarted = Dashboard(app.directory, lambda _: 0)
    assert restarted.version == "next-build" and restarted.instance_id != app.instance_id


def test_build_fingerprint_tracks_code_and_config_but_ignores_runtime_data(tmp_path):
    from alerters.techscout.version import app_version
    (tmp_path / "alerters").mkdir()
    code = tmp_path / "alerters" / "app.py"
    code.write_text("first")
    first = app_version(tmp_path)
    (tmp_path / "alerters" / "prices.json").write_text("private runtime data")
    assert app_version(tmp_path) == first
    code.write_text("second")
    assert app_version(tmp_path) != first
