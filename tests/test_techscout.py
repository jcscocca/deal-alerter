"""Shopping sessions must localize offers without joining the alert pipeline."""
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from alerters.techscout import __main__ as cli
from alerters.techscout.research import PRESETS, cpu_model, research
from alerters.techscout.walmart import Credentials, WalmartClient, WalmartError, response_items, validate_zip


@pytest.fixture(scope="module")
def credentials():
    return Credentials("12345678-1234-1234-1234-123456789abc", "1", rsa.generate_private_key(public_exponent=65537, key_size=2048))


class Response:
    def __init__(self, data, status=200):
        self.content = json.dumps(data).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.content


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def product(item_id="123", **changes):
    return {"itemId": item_id, "name": "MSI GeForce RTX 5080 16GB GDDR7 graphics card",
            "stock": "Available", "availableOnline": True, "salePrice": 2000,
            "sellerInfo": "Walmart.com", "conditionName": "New", "modelNumber": "GPU-1", **changes}


def test_signature_and_sanitized_audit(credentials):
    session, events = Session([Response({"items": [product()]})]), []
    client = WalmartClient(credentials, "94105", session=session, audit=events.append, clock=lambda: 123.456)
    assert client.lookup(["123"])[0]["itemId"] == "123"
    url, args = session.calls[0]
    assert url.endswith("/product/v2/items")
    assert args["params"] == {"ids": "123", "zipCode": "94105"}
    headers = args["headers"]
    credentials.private_key.public_key().verify(base64.b64decode(headers["WM_SEC.AUTH_SIGNATURE"]),
        f"{credentials.consumer_id}\n123456\n1\n".encode(), padding.PKCS1v15(), hashes.SHA256())
    assert args["allow_redirects"] is False
    assert session.trust_env is False
    assert "WM_" not in json.dumps(events) and credentials.consumer_id not in json.dumps(events)
    assert "consumer_id" not in repr(credentials)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_errors_do_not_retry_or_expose_bodies(credentials, status):
    session = Session([Response({"secret": "DO NOT PRINT"}, status)])
    client = WalmartClient(credentials, "94105", session=session)
    with pytest.raises(WalmartError, match=f"HTTP {status}") as error:
        client.lookup([123])
    assert "DO NOT PRINT" not in str(error.value)
    assert len(session.calls) == 1
    if status in (401, 403, 429):
        with pytest.raises(WalmartError):
            client.lookup([456])
        assert len(session.calls) == 1


def test_cache_and_request_budget(credentials):
    session = Session([Response({"items": [product()]})])
    client = WalmartClient(credentials, "94105", session=session, max_requests=1)
    assert client.lookup([123]) == client.lookup([123, 123])
    with pytest.raises(WalmartError, match="limit"):
        client.search("tablet")
    assert len(session.calls) == 1


@pytest.mark.parametrize("value", [None, 94105, "", "9810", "94105-1234", "94105&storeId=1"])
def test_explicit_zip_required(value):
    with pytest.raises(ValueError):
        validate_zip(value)


@pytest.mark.parametrize("data", [{"itemId": 123}, {"items": [{"itemId": 123}]}])
def test_live_flat_and_documented_envelope(data):
    assert response_items(data) == [{"itemId": 123}]


@pytest.mark.parametrize("data", [{}, {"items": None}, {"items": [1]}, []])
def test_malformed_products_not_treated_as_empty(data):
    with pytest.raises(WalmartError):
        response_items(data)


def test_lookup_rejects_unrequested_item(credentials):
    client = WalmartClient(credentials, "94105", session=Session([Response({"items": [product("456")]})]))
    with pytest.raises(WalmartError, match="unrequested"):
        client.lookup([123])


def test_load_protected_metadata_contract(tmp_path, credentials):
    key_path = tmp_path / "private.pem"
    key_path.write_bytes(credentials.private_key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    metadata = tmp_path / "application.json"
    raw = {"environment": "PRODUCTION", "consumer_id": credentials.consumer_id,
           "key_version": "1", "private_key_path": key_path.name}
    metadata.write_text(json.dumps(raw), encoding="utf-8-sig")
    assert Credentials.load(metadata).consumer_id == credentials.consumer_id
    raw["environment"] = "STAGING"
    metadata.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="Cannot load"):
        Credentials.load(metadata)


class FakeClient:
    zip_code = "94105"
    stopped = False

    def __init__(self, rows, discovery=None):
        self.rows, self.discovery = rows, discovery
        self.calls = []

    def search(self, query, limit):
        self.calls.append(("search", query))
        rows = self.rows if self.discovery is None else self.discovery
        return rows[:limit], 1000

    def lookup(self, ids):
        self.calls.append(("lookup", ids))
        return [row for row in self.rows if str(row["itemId"]) in ids]


def run(rows, **kwargs):
    return research(FakeClient(rows), queries=["computer parts"], seeds=[], **kwargs)


def test_parts_default_has_bounded_queries_and_no_saved_desktop_or_ram_plan(monkeypatch):
    from alerters.hardware.desktop_profile import DesktopProfile
    def forbidden(*args, **kwargs):
        pytest.fail("Parts research must not assess a completed desktop's RAM")
    monkeypatch.setattr(DesktopProfile, "assess_memory", forbidden)
    client = FakeClient([product(), product("124", name="Corsair Vengeance 64GB DDR5 memory kit")])
    result = research(client)
    searches = [arg for op, arg in client.calls if op == "search"]
    assert searches == list(PRESETS["parts"])
    assert set(PRESETS) == {"parts", "monitors", "memory", "supplies"}
    assert all(1 <= len(queries) <= 4 for queries in PRESETS.values())
    assert [arg for op, arg in client.calls if op == "lookup"] == [["123", "124"]]
    assert len(result.products) == 2  # repeated discovery is deduplicated
    assert all(p.memory_fit is None for p in result.products)
    assert "RAM kit" not in result.html()
    assert result.products[0].shipping is None


def test_search_price_never_used_when_localized_lookup_missing():
    client = FakeClient([], discovery=[product(salePrice=1)])
    result = research(client, queries=["graphics card"], seeds=[])
    assert not result.products
    assert any("not substituted" in p for p in result.problems)


def test_search_is_discovery_then_zip_localized_lookup(credentials):
    session = Session([Response({"items": [product(salePrice=1)], "totalResults": 999}),
                       Response({"items": [product(salePrice=2000)]})])
    client = WalmartClient(credentials, "94105", session=session)
    result = research(client, queries=["graphics card"], seeds=[])
    assert result.products[0].price == 2000
    assert "zipCode" not in session.calls[0][1]["params"]
    assert session.calls[1][1]["params"]["zipCode"] == "94105"
    assert result.coverage[0]["total"] == 999


def test_batch_limit_and_dedup():
    client = FakeClient([product(str(i + 1)) for i in range(25)])
    result = research(client, queries=["graphics card", "other parts"], seeds=[], limit=25)
    assert len(result.products) == 25
    assert [len(arg) for op, arg in client.calls if op == "lookup"] == [20, 5]


@pytest.mark.parametrize("category", PRESETS)
def test_complete_computers_excluded_even_from_custom_searches_and_explicit_ids(category):
    rows = [product("1", name="Gaming PC RTX 5080 Ryzen 7 9800X3D 32GB DDR5 1TB SSD"),
            product("2", name="RTX 5080 laptop 32GB RAM"),
            product("3", name="Apple iPad Air 256GB tablet"),
            product("4", name="Apple Mac mini M4 desktop computer"),
            product("5", name="MSI GeForce RTX 5090 32GB GDDR7 graphics card"),
            product("6", name="Samsung 32-inch 4K 144Hz gaming monitor"),
            product("7", name="Corsair Vengeance 64GB DDR5 desktop memory kit"),
            product("8", name="AMD Ryzen 9 9950X3D")]
    result = research(FakeClient(rows), category=category, queries=["desktop laptop tablet"], seeds=["1", "2", "3"])
    assert {p.item_id for p in result.products} == {"5", "6", "7", "8"}
    assert result.excluded == 4
    assert all(p.memory_fit is None for p in result.products)


def test_cpu_plus_suffix_retains_exact_model_helper():
    assert cpu_model("Intel Core Ultra 5 250KF Plus processor") == "ULTRA 5 250KF PLUS"
    assert cpu_model("Intel Core Ultra 5 250KF processor") == "ULTRA 5 250KF"


def test_generic_model_family_variants_not_averaged():
    result = run([product("1", name="Samsung 990 Pro NVMe SSD", modelNumber="SSD", attributes={"storage": "1TB"}),
                  product("2", name="Samsung 990 Pro NVMe SSD", modelNumber="SSD", attributes={"storage": "2TB"})])
    assert result.averages() == []


def test_malformed_credential_metadata_is_sanitized(tmp_path):
    metadata = tmp_path / "application.json"
    metadata.write_text("[]")
    with pytest.raises(ValueError, match="Cannot load"):
        Credentials.load(metadata)


def test_http_auth_failure_stops_entire_research(credentials):
    session = Session([Response({"error": "denied"}, 403)])
    result = research(WalmartClient(credentials, "94105", session=session))
    assert len(session.calls) == 1 and not result.products
    assert "403" in result.problems[0]


def test_oversized_response_is_rejected(credentials, monkeypatch):
    from alerters.techscout import walmart
    monkeypatch.setattr(walmart, "MAX_RESPONSE", 10)
    client = WalmartClient(credentials, "94105", session=Session([Response(product())]))
    with pytest.raises(WalmartError, match="size limit"):
        client.lookup([123])


def test_averages_are_comparable_current_offers_only():
    result = run([product("1", salePrice=2000), product("2", salePrice=2400),
                  product("3", salePrice=1, availableOnline=False),
                  product("4", salePrice=10, stock="Not available"),
                  product("5", salePrice=500, conditionName="Refurbished"),
                  product("6", salePrice=100, sellerInfo=None),
                  product("7", name="MSI GeForce RTX 5090 32GB GDDR7 graphics card"),
                  product("8", name="Choose your RTX 5080 graphics card configuration")])
    stats = result.averages()
    assert len(stats) == 1 and stats[0]["count"] == 2 and stats[0]["mean_item_price"] == 2200
    assert stats[0]["item_ids"] == ["1", "2"]
    assert "not a historical discount or deal verdict" in result.html()


def test_marketplace_alternative_is_not_selected_offer():
    row = product(salePrice=None, bestMarketplacePrice={"price": 1, "sellerInfo": "Another seller"})
    assert run([row]).products[0].price is None


@pytest.mark.parametrize("category", PRESETS)
def test_categories_share_research_cards_without_ram_completion(category):
    result = run([product("1", name="Corsair Vengeance 32GB DDR5 desktop memory kit", modelNumber="DDR5")], category=category)
    assert result.products[0].memory_fit is None
    assert "Corsair Vengeance" in result.html()
    assert "RAM compatibility" not in result.html()


def test_report_escapes_api_content_and_does_not_use_api_urls():
    result = run([product("1", name='<script>attack()</script> gaming monitor', productUrl="file:///private")], category="monitors")
    html = result.html()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "file:///" not in html and 'https://www.walmart.com/ip/1' in html


@pytest.mark.parametrize("kwargs", [{"queries": []}, {"queries": ["x"] * 5 + ["y"] * 5, "limit": 26},
                                    {"queries": ["a", "b", "c", "d", "e"]}, {"limit": 0}])
def test_invalid_plans_make_no_calls(kwargs):
    client = FakeClient([])
    with pytest.raises(ValueError):
        research(client, **kwargs)
    assert client.calls == []


def test_cli_creates_parts_snapshot_without_prebuilt_history_or_notifications(tmp_path, monkeypatch, credentials):
    from alerters.techscout import price_history
    def forbidden(*args, **kwargs):
        pytest.fail("The active research CLI must not write whole-PC price history")
    monkeypatch.setattr(price_history, "record_research", forbidden)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"walmart": {"zip_code": "94105", "credential_file": "fake.json"}}))
    session = Session([Response({"items": [product(standardShipRate=0)]}), Response({"items": [product(standardShipRate=0)]})])
    monkeypatch.setattr(cli.Credentials, "load", lambda _: credentials)
    monkeypatch.setattr(cli, "WalmartClient", lambda cred, zipcode, audit: WalmartClient(cred, zipcode, audit=audit, session=session))
    output = tmp_path / "reports"
    args = ["--settings", str(settings), "--output", str(output), "--query", "graphics card", "--item-id", "123"]
    assert cli.main(args) == 0
    assert session.closed
    assert {p.name for p in output.iterdir()} == {"latest-parts.html", "latest-parts.json", "latest-parts.requests.json"}
    receipt = (output / "latest-parts.requests.json").read_text()
    assert "WM_" not in receipt and credentials.consumer_id not in receipt
    assert json.loads((output / "latest-parts.json").read_text())["products"][0]["price"] == 2000


def test_missing_settings_fail_without_network(tmp_path, capsys):
    assert cli.main(["--settings", str(tmp_path / "missing.json")]) == 2
    assert "No requests made" in capsys.readouterr().err
