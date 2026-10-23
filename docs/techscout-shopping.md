# TechScout: standout parts and monitor deals

TechScout is a local tech-deal browser centered on unusually good individual-part
and monitor offers. CPUs, GPUs, memory, storage and useful peripherals can be
browsed without tying them to a completed computer build. Complete desktops,
laptops and tablets are excluded from new research and loaded shopping results.
The prebuilt searches, whole-build comparisons and owned-RAM completion controls
are retired from the active experience. Existing historical data is preserved.

Repository changes require the existing [ThinkPad Prepare/Update
procedure](thinkpad-monitor.md) before they affect the installed monitor or
shortcuts. Development and tests do not deploy or change scheduled tasks.

## Open the dashboard

```powershell
python -m alerters.techscout --serve
```

Open [TechScout on this computer](http://127.0.0.1:8768/). Keep the process running;
Ctrl+C stops it. `--port` selects another local port. The server binds only to
`127.0.0.1`, serves a fixed set of assets and rejects invalid Host/origin headers.
It is available only on this computer.

On Windows, the dashboard reads the installed monitor's public
`C:\ProgramData\DealAlerter\shopping-sources.json`; `--monitor-runtime` selects
another installation. The monitor must be updated to publish this snapshot.
The browser receives shopping fields, source health and delivery decisions.
It does not receive keys, raw API responses or the protected runtime's history
and notification settings.

The feed combines the monitor's eligible component/monitor finds, saved Walmart
research and publisher/community reports. Category and specification filters
help browse parts, monitors, memory and supplies. A RAM capacity filter describes
an individual product; there is no owned-kit reuse preference or build-completion
rule. Saved comparisons hold up to three candidates in the browser.

## Deal evidence and alerts

Standout deals require a qualifying `EXCEPTIONAL`/`GRAIL` price verdict, or a
verified monitor offer at least 25% below its exact model’s dated retail quote,
plus current retailer evidence. Each card names its evidence; a dated retail
quote is not sold-market value. A target hit is identified separately. Exact part/model, condition,
seller, positive price, shipping, stock and freshness matter; a price quote or
retail discount badge alone does not establish a good deal.

The broader browse results include ordinary offers, unassessed research, stale or
unavailable listings, and publisher leads. Each retains its evidence and status.
Walmart product research is browse-only; generic MSRP is never treated as proof
of a current discount. Unknown shipping remains unknown, and saved prices are
not presented as current checkout totals. Community and publisher reports do not
establish seller, condition, inventory or final price.

The assessed component catalog and enabled hunts define automatic verdict
coverage. Broader discovery can show CPUs, SSDs, motherboards, memory and other
parts without claiming they have a price-history judgment. The existing
[4K monitor watch](4k-monitor-watch.md) has its own specifications and exact-model
benchmark requirements; a broader browse filter does not expand those alerts.
Individual-component deals no longer need to increase the completed rig's memory
capacity to be interesting.

**Watching** saves up to 40 product/search preferences, price limits and filters.
These narrow existing monitor coverage and do not start new retailer searches.
**All exceptional deals & price-target notices** allows exceptional monitored
deals and separately identified configured target hits;
**Only enabled watches** narrows delivery to matching watches, and zero enabled
watches means zero deal notifications. **Pause deal notifications** suspends deal
delivery while collection continues. Source-health warnings remain separate.
Changes apply when the monitor next reads preferences. The installed monitor
must advertise watch-settings version 2 before the dashboard can save changes;
an older installation remains readable without rewriting its settings. None of these choices
relaxes evidence or engine qualification rules. Walmart and publisher-only finds
remain browse-only.

The dashboard writes validated, non-secret preferences only to `ui/watches.json`
in the selected runtime. An absent preferences file keeps the normal all-deals
mode; a malformed one pauses deal delivery until repaired. Old desktop and tablet
watch entries cannot reintroduce out-of-scope offers.

**Alerts** shows retained successful sends and failures, and the latest delivery
decisions for loaded monitored offers. Sent means a transport accepted the
notification, not that the user read it. History is bounded and is not a complete
historical inbox. **Sources** shows enabled coverage, recent checks and failures.

## Refresh and source limits

The browser rereads local results every 15 seconds without retailer requests.
**Check Walmart now** runs the selected category's bounded preset searches,
then ZIP-localized product lookups and replaces that category's snapshot.
Opening the dashboard or changing filters does not call Walmart. One manual
check runs at a time, with a 30-second pause between starts; failure does not make
an older snapshot fresh. A Walmart snapshot expires from current-offer ranking
after 15 minutes, even if the page stays open.

The installed monitor retains its own schedules, backoff and notification
ownership. Sources expire independently; a failed Walmart request does not make
a fresh monitored offer stale. Monitor freshness follows its collection interval,
and failed or overdue source checks remain visible. Reloading local results
cannot refresh inventory. The monitor continues to run when the dashboard is
closed; the dashboard creates no second monitoring task.

While the dashboard runs, its background worker checks public publisher feeds
about every 15 minutes and stores a bounded local cache in
`reports/deal-feeds.json`. Recent component, monitor and peripheral reports are
leads, with original publisher links, quoted prices and reported terms retained.
Explicit retailer attribution identifies Amazon reports; a comparison link does
not identify a retailer. Matching product identifiers/names can combine publisher
reports, while different configurations and conditions remain separate. Combined
reports do not become inventory checks or market-price samples. Feed reports
expire after 72 hours; failed or older checks keep their uncertainty visible.
No publisher reports send alerts through the dashboard.

## Windows shortcut and automatic startup

First deploy the merged application with the existing monitor Prepare/Update
procedure. Shortcut setup creates a separate per-user virtual environment with
`requirements-techscout.txt`, keeping the monitor environment unchanged. From the
ordinary account that will use TechScout,
obtain its SID with `[Security.Principal.WindowsIdentity]::GetCurrent().User.Value`.
Then run this once from an administrator PowerShell, substituting that SID:

```powershell
& 'C:\ProgramData\DealAlerter\app\scripts\windows\Enable-TechScoutControls.ps1' -UserSid 'YOUR_WINDOWS_ACCOUNT_SID'
```

This grants that account Modify access only to `C:\ProgramData\DealAlerter\ui`,
which contains validated watch preferences. The protected application, secrets,
notification receipts and price history keep their existing permissions.
Back in ordinary PowerShell, install the per-user shortcuts:

```powershell
& 'C:\ProgramData\DealAlerter\app\scripts\windows\Install-TechScout.ps1'
& "$env:LOCALAPPDATA\TechScout\Start-TechScout.ps1" -OpenBrowser
```

The desktop and Start menu **TechScout** shortcuts start the local dashboard if
needed and open it. The Startup shortcut starts it silently at sign-in. Use
`-DataDirectory` to retain an existing TechScout data folder at a different physical
path, including one redirected by a packaged desktop app. No settings or keys
are copied. Use
`-NoStartup` when installing if you only want launch shortcuts. To turn automatic
startup off later, remove TechScout from the Windows Startup folder. Repeated
launches reuse the same listening dashboard. Logs are under
`%LOCALAPPDATA%\TechScout\logs`. The protected hardware monitor continues to run
through its existing tasks, including when the dashboard is closed.

## Local setup

Use Python 3.11+ in a virtual environment:

```powershell
python -m pip install -r requirements-techscout.txt
python -m alerters.techscout
```

The optional signing dependency is separate from the monitor's requirements.
Keep the RSA private key and settings outside the repository. On Windows the
default settings path is `%LOCALAPPDATA%\TechScout\settings.json`; on other
systems it is `~/.local/share/TechScout/settings.json`. Example (placeholders):

```json
{
  "walmart": {
    "zip_code": "YOUR_FIVE_DIGIT_ZIP",
    "credential_file": "credentials/walmart-production/application.json"
  }
}
```

The credential metadata file references a local RSA PEM key of at least 2048 bits:

```json
{
  "environment": "PRODUCTION",
  "consumer_id": "YOUR_CONSUMER_UUID",
  "key_version": "1",
  "private_key_path": "private-key.pem"
}
```

Relative paths resolve beside their containing JSON file. Restrict access to the
credential directory using OS permissions. Register the corresponding public key
with Walmart; do not paste or upload the private key. The existing local TechScout
setup on this ThinkPad already supplies the production credential and selected ZIP.

## Choose a research task

```powershell
# Default: CPU, GPU and SSD searches.
python -m alerters.techscout

python -m alerters.techscout --category monitors
python -m alerters.techscout --category memory
python -m alerters.techscout --category supplies

# Replace preset searches with the products you are researching.
python -m alerters.techscout --category parts --query "AMD Ryzen 9 9950X3D"
python -m alerters.techscout --category monitors --query "32 inch 4K 144Hz monitor" --limit 5
python -m alerters.techscout --category memory --query "DDR5 64GB 2x32GB memory kit"
```

The presets are **parts**, **monitors**, **memory** and **supplies**. Each has at
most four searches. `--query` replaces the preset and may repeat up to four times;
`--limit` selects 1–25 search results per query (default 10). `--item-id` adds
explicit product IDs for lookup, with up to 20 numeric IDs. There are no saved
desktop seed IDs. The parts/peripherals scope also applies to custom searches
and explicit IDs, so a broad search cannot bring complete PCs back.

Use `--settings`, `--zip-code` and `--output` to override local defaults.
The default run writes `reports/latest-parts.html`, `latest-parts.json` and
`latest-parts.requests.json` beneath the TechScout data directory. Other presets
use their own category names. Each run replaces its three files and neither
sends notifications nor writes prebuilt/whole-PC price history.

Request receipts record actual purpose, queries, IDs, ZIP and HTTP status.
They omit authorization headers, signatures, consumer ID, response bodies and
private keys. Reports and receipts are local personal data and are not committed.

Exit codes: `0` is a nonempty report without request/lookup gaps; `1` is empty or
partial research; `2` is a settings, arguments or output error. A successful run
does not mean every product is available or that the catalog was fully searched.

## Walmart research evidence

Search discovers product IDs; its quoted prices never enter the report. Each
product needs a subsequent ZIP-localized lookup. Missing lookup results are
reported instead of falling back to a search price. At most 12 requests are
allowed in a session, with at most 20 IDs per lookup. Requests are deduplicated
and cached only for that session. Redirects and automatic retries are disabled;
HTTP 401, 403 or 429 stops the session. These are local bounds, not an account
quota statement.

Cards display the selected seller, condition, price, shipping and availability.
Tax, alternate marketplace offers, memberships, coupons and checkout charges
are not inferred. At least two distinct available offers need matching model,
title, condition and published attributes for a standalone report's sample mean.
Unknown sellers, ambiguous configurations, unavailable products and invalid
prices are excluded. These means describe only the inspected current item prices
before shipping/tax; they are not market averages, historical baselines or deal
verdicts. Coverage is shown explicitly.

Local snapshots and credentials should continue to follow the account holder's
Walmart application terms and the existing protected-directory permissions.

## Validation

```powershell
python -m pytest -q tests/test_techscout.py tests/test_techscout_dashboard.py tests/test_standout_pipeline.py
python -m pytest -q tests/test_deal_feeds.py tests/test_shopping_sources.py tests/test_shopping_integration.py
python -m pytest -q tests/test_techscout_facets.py tests/test_techscout_browsing.py
node --test tests/techscout_browsing.test.cjs
```

Tests use generated keys and fake sessions without production credentials or
network. They cover signed requests, access failures, request bounds,
ZIP-localized evidence, whole-computer exclusions, individual-part preservation,
comparable models, escaped cards, local output and the absence of prebuilt-history
writes or RAM-completion assessment in active research. Dated retailer and
prebuilt investigations elsewhere in `docs/` remain historical records.
