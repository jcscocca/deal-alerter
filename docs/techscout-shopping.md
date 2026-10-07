# TechScout shopping research

TechScout creates a current shopping report when you run it. The first workflow
compares RTX 5080/5090 desktops and assesses reuse of the owned Corsair 64GB DDR5
kit. The same product cards support tablets, other computers, memory, monitors,
docks and other tech supplies through selectable searches.

The local dashboard adds a ranked shortlist, saved finalists and a side-by-side
comparison view. Start it from the repository's virtual environment:

```powershell
python -m alerters.techscout --serve
```

Open [TechScout on this computer](http://127.0.0.1:8768/). Keep the process running
while using the page; Ctrl+C stops it. After restarting the computer, run the
command again. `--port` selects another local port. No account or public hosting
is needed, and the page is not accessible from another computer or phone.

The page combines saved Walmart research with the running hardware monitor's
public shopping snapshot. On Windows it reads
`C:\ProgramData\DealAlerter\shopping-sources.json`; `--monitor-runtime` selects
another runtime. The monitor must be upgraded to the version that publishes this
file. No API credentials, notification settings, history files, or raw API bodies
are exposed to the browser. The dashboard never writes monitor state.

**All monitor deals** shows the existing watchlist's eBay/Apple hardware results,
Newegg desktops, and community leads. Other category views include matching
monitor products alongside Walmart. Use **Source** to narrow the list; retailer,
seller, condition and check time appear on every card. Complete desktops and loose
components remain in separate groups. Listings with the same ID in different
sources do not overwrite each other; exact duplicate source identities collapse.
Different retailer/seller offers remain separately comparable.

The browser rereads local monitor results every 15 seconds without additional
retailer requests. The collector retains its existing schedules, backoff and
notification behavior. HP and Reddit remain visible as unavailable until their
access actually recovers. Slickdeals/Reddit posts appear under **Community leads**,
never as confirmed inventory. eBay variants, risky sellers, multi-item lots, and
missing shipping quotes remain held. Apple's current collector does not establish
shipping, so its finds remain visible outside the delivered-price ranking.

**Check Walmart now** runs only the selected
category's preset searches (10 results per search), then replaces its snapshot.
Opening the page, changing categories and checking refresh progress do not make
Walmart calls. Custom CLI searches remain available through the commands below;
the dashboard button always uses presets. One check runs at a time, with a
30-second pause between starts. Failed checks are recorded locally and do not
make an older snapshot look newly available. A check interrupted by server
shutdown also leaves its previous snapshot outside the current ranking.

## How the dashboard ranks

- Main rankings require availability from a recent retailer check,
  a positive price, known shipping, seller and condition, and a snapshot no older
  than 15 minutes for Walmart. Monitor freshness follows its collection interval
  plus 90 seconds (at least 15 minutes, at most 61.5 minutes for hourly Apple checks).
  A failed source or a monitor heartbeat older than 90 seconds holds its offers. Expired results move outside the ranking even if the page is
  left open; only a manual check retrieves new Walmart data. Each source expires
  independently, so a failed Walmart request cannot invalidate fresh Newegg results.
- Desktop rankings are separate for each GPU, factory RAM capacity and condition.
  Configurations must remain eligible under the owned-memory profile. Documented
  physical RAM layouts rank first; within each evidence level, lower price plus
  shipping ranks first. CPU, storage, motherboard, warranty and seller can differ.
  “Why this rank?” explains the rule; it does not claim benchmark superiority or
  a historical discount. Mixed-kit compatibility still needs verification.
- Other categories show price order within condition, with an explicit warning
  that unlike models are not equivalent in performance or value. Known tablet
  storage mismatches are held for verification.
- Missing details, unavailable items and stale offers remain in **Outside the
  ranking**. They can be saved for comparison, with their warnings preserved.
- Save up to three finalists in the browser. Only their product IDs are stored
  in local storage. If a saved ID disappears from the current results, the page
  reports it as missing instead of displaying an old price.

The server binds only to `127.0.0.1`. It serves a fixed set of assets and a public
shopping-field projection, never arbitrary files or credential metadata. Refresh
requires the local page's token and matching origin; mismatched Host headers are
rejected. `dashboard-last-check.json` contains only the latest per-category check
status and time, with no prices or authentication data. Keep credentials in the
existing protected directory. The local server does not start at Windows login.

This is independent of the installed alert monitor: it creates no tasks, sends
no notifications, and writes no price history or monitor state. It does not read
`.env` or `secrets.env`. The reports contain current API evidence, not fabricated
traffic or a claim that an application description grants additional rights.
Account access alone is not approval of downstream uses; the account holder
must keep actual use and application information aligned with applicable
[Walmart API terms](https://walmart.io/termsandcondition) and, where applicable,
[affiliate terms](https://affiliates.walmart.com/terms).

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

## Choose a shopping task

```powershell
# Default: desktop candidates plus the exact owned memory kit as a reference.
python -m alerters.techscout

# Broader categories are on demand, never rotated for background traffic.
python -m alerters.techscout --category tablets
python -m alerters.techscout --category computers
python -m alerters.techscout --category supplies
python -m alerters.techscout --category memory

# Replace preset queries with the actual product you are researching.
python -m alerters.techscout --category supplies --query "USB C 100W charger"
python -m alerters.techscout --category tablets --query "iPad Air 256GB" --limit 5
```

`--query` may repeat up to four times. `--limit` bounds results per search to 1–25
(default 10). `--item-id` replaces saved candidate IDs; up to 20 numeric IDs may
be supplied. Category presets are discovery queries, not a guarantee of complete
or relevant results. Desktop mode filters for supported desktops or the exact
owned memory model; other modes display returned product candidates for review.
Use `--settings`, `--zip-code` or `--output` to override local defaults.

Open `%LOCALAPPDATA%\TechScout\reports\latest-desktop-memory.html` after the
default run. Each category overwrites three files: the latest HTML report, JSON
product snapshot, and request receipt (`.requests.json`). Receipts record the
actual purpose, queries, IDs, ZIP and HTTP status, without authorization headers,
signatures, consumer ID, response bodies or private keys. Reports and receipts
are local personal data; they are not committed or appended into history.

Exit codes: `0` means a nonempty report with no request/lookup gaps; `1` means an
empty or partial report (inspect it); `2` means settings, arguments or output
could not be used. A successful run does not imply any product is in stock or
that the entire catalog has been searched.

## Evidence and limits

- [Search](https://www.walmart.io/docs/affiliates/v1/search) discovers IDs. Search
  prices never enter the report. Each result must pass a subsequent
  [product lookup](https://www.walmart.io/docs/affiliates/v1/product-lookup) with
  the selected ZIP. Missing lookup results are reported as gaps.
- At most 12 network requests are allowed per session, with at most 20 IDs in a
  lookup. Duplicate requests are cached only for that session. Redirects are
  disabled. There are no automatic retries; 401, 403 or 429 stops further calls.
  These bounds are local controls, not a statement of account quota.
- Cards show seller, condition, current item price and availability. Shipping
  that is absent stays unknown. Tax, alternative marketplace seller prices,
  memberships, coupons and checkout charges are not inferred. A tablet search
  can match a parent listing while lookup selects a different storage variant;
  explicit capacity mismatches are flagged and excluded from averages.
- Averages need at least two distinct, available offers with identified sellers,
  conditions and positive prices. Desktop cohorts match CPU, GPU, installed DDR5
  RAM capacity and SSD capacity; other components can differ. Other products require
  matching model, title, condition and returned attributes. These are selected
  sample means of current item prices before shipping/tax, not market averages
  or historical price baselines. Sparse or ambiguous specifications produce no
  average. Search coverage is shown explicitly.
- Desktop RAM checks reuse `config/desktop-profile.toml`: factory 32GB or 64GB,
  owned 2×32GB DDR5, four slots and a possible 96GB/128GB total. Off-plan systems
  are labeled. Missing layout evidence stays **NEEDS SPECS**. Even a documented
  physical fit does not verify mixed-kit stability or memory speed. No new kit
  purchase is added to the default desktop budget.

## Validation

```powershell
python -m pytest -q tests/test_techscout.py tests/test_techscout_dashboard.py
```

Tests use generated test keys and fake API sessions, with no real credentials or
network. They cover signed canonical bytes, access failures, ZIP localization,
request bounds, deduplication, comparable cohorts, RAM reuse, escaped cards and
local CLI output. Live October 6, 2026 validation produced 18 desktop cards from
five API calls; the saved $2,299 CyberPower candidate was unavailable and the exact
owned Corsair kit search returned no results. A focused tablet search produced
three cards in two calls, including default 128GB variants from a 256GB query;
the report flags that mismatch. Those observations are a dated
validation record, not current availability promises.
