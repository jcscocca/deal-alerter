"""Shopping sessions must localize offers without joining the alert pipeline."""
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from alerters.techscout import __main__ as cli
from alerters.techscout.research import research
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
    return {"itemId": item_id, "name": "Gaming PC RTX 5080 Ryzen 7 9800X3D 32GB DDR5 1TB SSD",
            "stock": "Available", "availableOnline": True, "salePrice": 2000,
            "sellerInfo": "Walmart.com", "conditionName": "New", "modelNumber": "PC-1", **changes}


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
    return research(FakeClient(rows), queries=["desktop"], seeds=[], **kwargs)


def test_desktop_default_starts_with_owned_ram_plan():
    client = FakeClient([product()])
    result = research(client)
    searches = [arg for op, arg in client.calls if op == "search"]
    assert searches == ["RTX 5080 gaming desktop", "RTX 5090 gaming desktop", "CMH64GX5M2B6000C40W"]
    assert len(result.products) == 1  # same item across all searches
    fit = result.products[0].memory_fit
    assert fit["potential_gb"] == 96 and fit["status"] == "NEEDS SPECS"
    assert result.products[0].shipping is None


def test_search_price_never_used_when_localized_lookup_missing():
    client = FakeClient([], discovery=[product(salePrice=1)])
    result = research(client, queries=["desktop"], seeds=[])
    assert not result.products
    assert any("not substituted" in p for p in result.problems)


def test_search_is_discovery_then_zip_localized_lookup(credentials):
    session = Session([Response({"items": [product(salePrice=1)], "totalResults": 999}),
                       Response({"items": [product(salePrice=2000)]})])
    client = WalmartClient(credentials, "94105", session=session)
    result = research(client, queries=["desktop"], seeds=[])
    assert result.products[0].price == 2000
    assert "zipCode" not in session.calls[0][1]["params"]
    assert session.calls[1][1]["params"]["zipCode"] == "94105"
    assert result.coverage[0]["total"] == 999


def test_batch_limit_and_dedup():
    client = FakeClient([product(str(i + 1)) for i in range(25)])
    result = research(client, queries=["desktop", "other desktop"], seeds=[], limit=25)
    assert len(result.products) == 25
    assert [len(arg) for op, arg in client.calls if op == "lookup"] == [20, 5]


def test_owned_memory_and_unmatched_results():
    result = run([product(), product("124", name="Corsair CMH64GX5M2B6000C40W memory kit"),
                  product("125", name="RTX 5080 laptop 32GB RAM"), product("126", name="RTX 5090 GPU 32GB GDDR7")])
    assert len(result.products) == 2 and result.excluded == 2
    assert any("Owned-kit reference" in w for p in result.products for w in p.warnings)


def test_ram_reuse_requires_published_layout():
    row = product(attributes={"ramMemory": "32GB DDR5 (2 x 16GB)", "memorySlots": "4",
                              "maximumMemorySupported": "128GB"})
    fit = run([row]).products[0].memory_fit
    assert fit["status"] == "POSSIBLE REUSE" and "unverified" in fit["summary"]
    outside = run([product(name="Gaming PC RTX 5080 128GB DDR5 1TB SSD")]).products[0]
    assert outside.memory_fit["eligible"] is False
    assert outside.comparison_key is None


def test_vram_is_not_system_ram():
    row = product(name="Gaming PC RTX 5090 32GB GDDR7 9800X3D 2TB SSD")
    fit = run([row]).products[0].memory_fit
    assert fit["installed_gb"] is None and fit["potential_gb"] is None


def test_unknown_memory_generation_not_averaged_with_ddr5():
    result = run([product("1"), product("2", name="Gaming PC RTX 5080 9800X3D 32GB RAM 1TB SSD")])
    assert result.averages() == []


def test_cpu_plus_suffix_keeps_different_models_out_of_same_average():
    result = run([product("1", name="Gaming PC RTX 5080 Core Ultra 5 250KF Plus 32GB DDR5 1TB SSD"),
                  product("2", name="Gaming PC RTX 5080 Core Ultra 5 250KF 32GB DDR5 1TB SSD")])
    assert result.products[0].comparison_key[2] == "ULTRA 5 250KF PLUS"
    assert result.averages() == []


def test_conflicting_ram_attributes_require_review():
    fit = run([product(attributes={"ramMemory": "32GB DDR5", "ramMemorySize": "64GB"})]).products[0].memory_fit
    assert fit["status"] == "NEEDS SPECS" and fit["installed_gb"] is None


def test_generic_model_family_variants_not_averaged():
    result = run([product("1", name="Tablet", modelNumber="TAB", attributes={"storage": "128GB"}),
                  product("2", name="Tablet", modelNumber="TAB", attributes={"storage": "256GB"})], category="tablets")
    assert result.averages() == []


def test_tablet_default_variant_mismatch_is_flagged():
    result = research(FakeClient([product("1", name="iPad Air 128GB", modelNumber="TAB")]),
                      category="tablets", queries=["iPad Air 256GB"], seeds=[])
    assert result.products[0].comparison_key is None
    assert any("differs" in warning for warning in result.products[0].warnings)


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
                  product("7", name="Gaming PC RTX 5090 9800X3D 32GB DDR5 1TB SSD"),
                  product("8", name="Gaming PC RTX 5080 9800X3D 64GB DDR5 1TB SSD"),
                  product("9", name="Gaming PC RTX 5080 9800X3D 32GB DDR5 2TB SSD")])
    stats = result.averages()
    assert len(stats) == 1 and stats[0]["count"] == 2 and stats[0]["mean_item_price"] == 2200
    assert stats[0]["item_ids"] == ["1", "2"]


def test_marketplace_alternative_is_not_selected_offer():
    row = product(salePrice=None, bestMarketplacePrice={"price": 1, "sellerInfo": "Another seller"})
    assert run([row]).products[0].price is None


@pytest.mark.parametrize("category", ["tablets", "computers", "supplies", "memory"])
def test_categories_share_cards_but_not_desktop_rules(category):
    result = run([product("1", name="Tablet 128GB Wi-Fi", modelNumber="TAB1")], category=category)
    assert result.products[0].memory_fit is None
    assert "Tablet 128GB Wi-Fi" in result.html()


def test_report_escapes_api_content_and_does_not_use_api_urls():
    result = run([product("1", name='<script>attack()</script> tablet', productUrl="file:///private")], category="tablets")
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


def test_cli_creates_local_snapshot_without_notifications(tmp_path, monkeypatch, credentials):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"walmart": {"zip_code": "94105", "credential_file": "fake.json"}}))
    session = Session([Response({"items": [product()]}), Response({"items": [product()]})])
    monkeypatch.setattr(cli.Credentials, "load", lambda _: credentials)
    monkeypatch.setattr(cli, "WalmartClient", lambda cred, zipcode, audit: WalmartClient(cred, zipcode, audit=audit, session=session))
    output = tmp_path / "reports"
    args = ["--settings", str(settings), "--output", str(output), "--query", "desktop", "--item-id", "123"]
    assert cli.main(args) == 0
    assert session.closed
    assert {p.name for p in output.iterdir()} == {"latest-desktop-memory.html", "latest-desktop-memory.json", "latest-desktop-memory.requests.json"}
    receipt = (output / "latest-desktop-memory.requests.json").read_text()
    assert "WM_" not in receipt and credentials.consumer_id not in receipt
    assert json.loads((output / "latest-desktop-memory.json").read_text())["products"][0]["price"] == 2000


def test_missing_settings_fail_without_network(tmp_path, capsys):
    assert cli.main(["--settings", str(tmp_path / "missing.json")]) == 2
    assert "No requests made" in capsys.readouterr().err
