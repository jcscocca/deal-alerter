from datetime import datetime, timezone
from pathlib import Path

import pytest

from alerters.hardware.community import parse_slickdeals_computers, SLICKDEALS_COMPUTERS
from alerters.hardware.monitor_sources import fetch_feed
from alerters.hardware.monitor import Monitor, job_id
from alerters.hardware.retail_http import Deferred, Robots

NOW = datetime(2026, 10, 6, 3, 40, tzinfo=timezone.utc)
FIXTURE = Path(__file__).with_name("fixtures") / "slickdeals_computers.html"


def test_observed_public_category_retains_post_time_id_price_and_unverified_evidence():
    rows = parse_slickdeals_computers(FIXTURE.read_text(encoding="utf8"), NOW)
    assert len(rows) == 1
    assert rows[0].source == "slickdeals"
    assert rows[0].listing_id.isdigit()
    assert rows[0].posted_at < NOW
    assert "$" in rows[0].title
    assert rows[0].extra == {"coverage": "computers-category-first-page"}


def page(*, expiry="0", posted="1791253458", href="/f/123-rtx-5090-pc", title="RTX 5090 Gaming PC"):
    return f'''<ul class="bp-p-filterGrid_items"><li class="bp-p-dealCard" data-catalog-item="DealCard"
      data-label-expired="{expiry}" data-posted-at="{posted}"><a class="bp-c-card_title" href="{href}">{title}</a>
      <span class="bp-p-dealCard_price">$4,299.99</span></li></ul>'''


@pytest.mark.parametrize("changes", [
    {"expiry": "1"}, {"expiry": "unknown"}, {"posted": "invalid"},
    {"posted": "1"}, {"posted": "999999999999999999999999"},
    {"posted": str(int(NOW.timestamp()) + 1)}, {"title": ""},
    {"href": "https://evil.test/f/123-rtx-5090-pc"}, {"href": "//evil.test/f/123-rtx-5090-pc"},
    {"href": "https://user@slickdeals.net/f/123-rtx-5090-pc"},
    {"href": "/f/123-rtx-5090-pc?page=2"}, {"href": "/click?thread=123"},
])
def test_unsafe_or_stale_category_evidence_is_excluded(changes):
    assert parse_slickdeals_computers(page(**changes), NOW) == []


def test_duplicates_do_not_create_multiple_observations_and_card_price_is_explicit():
    body = page().replace("</ul>", page().split(">", 1)[1])
    rows = parse_slickdeals_computers(body, NOW)
    assert len(rows) == 1
    assert rows[0].title.endswith(" - $4,299.99")
    # A title's advertised price cannot be overwritten by a different card price.
    assert parse_slickdeals_computers(page(title="RTX 5090 PC $3999"), NOW)[0].title.endswith("$3999")


@pytest.mark.parametrize("body", ["<html>challenge</html>", '<ul class="bp-p-filterGrid_items"></ul>'])
def test_schema_failure_is_deferred_instead_of_reporting_quiet_market(body):
    with pytest.raises(Deferred):
        parse_slickdeals_computers(body, NOW)


def test_fetch_uses_allowed_category_and_reports_coverage_limit():
    calls = []
    class Client:
        def get(self, url):
            calls.append(url)
            return page()
    batch = fetch_feed("slickdeals", Client(), NOW)
    assert calls == [SLICKDEALS_COMPUTERS]
    assert len(batch.listings) == 1
    assert "page only" in batch.notes[0]
    robots = Robots("User-agent: *\nDisallow: /newsearch.php?*rss=*\nDisallow: /*page=*")
    assert robots.allows(SLICKDEALS_COMPUTERS)
    assert not robots.allows("https://slickdeals.net/newsearch.php?q=5090&rss=1")


def test_category_route_is_not_delayed_by_retired_rss_path_backoff(tmp_path, monkeypatch):
    import json
    import time
    from pathlib import Path
    monkeypatch.setattr("alerters.hardware.monitor.channels", lambda **_: ())
    until = time.time() + 21600
    (tmp_path / "schedule.json").write_text(json.dumps({
        "jobs": {job_id("slickdeals"): {"kind": "slickdeals", "next": until, "failures": 5,
                                       "error": "Path disallowed by robots.txt"}},
        "host_backoff": {"slickdeals.net": until + 60},
    }))
    root = Path(__file__).resolve().parents[1]
    mon = Monitor(root / "config/monitor.toml", tmp_path / "state", tmp_path, dry_run=False)
    job = mon.jobs[job_id("slickdeals", SLICKDEALS_COMPUTERS)]
    assert job["next"] == 0 and job["failures"] == 0
    assert job["url"] == SLICKDEALS_COMPUTERS
    assert job_id("slickdeals") not in mon.jobs
    # Changing a path does not erase a shared server/host cooldown.
    assert mon.client.host("slickdeals.net")["blocked_until"] == until + 60
