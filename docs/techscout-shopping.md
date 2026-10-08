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
while using the page; Ctrl+C stops it. For automatic startup and a desktop shortcut on the installed Windows monitor,
use the setup below. Otherwise run the command again after restarting. `--port` selects another local port. No account or public hosting
is needed, and the page is not accessible from another computer or phone.
Only one dashboard can listen on a port; Windows uses an exclusive socket so an
older server cannot silently share requests with a newer one.

The page combines saved Walmart research with the running hardware monitor's
public shopping snapshot. On Windows it reads
`C:\ProgramData\DealAlerter\shopping-sources.json`; `--monitor-runtime` selects
another runtime. The monitor must be upgraded to the version that publishes this
file. No API credentials, notification settings, history files, or raw API bodies
are exposed to the browser. The dashboard only writes the bounded, non-secret
`ui/watches.json` preferences through the Watching view; delivery receipts and
monitor price history remain owned by the monitor. Explicit Walmart research
runs also maintain a separate local complete-PC history, described below.

**All deals** combines saved Walmart research across categories with the existing
watchlist's eBay/Apple hardware results, Newegg/CyberPowerPC/Skytech desktops,
iBUYPOWER catalog quotes, and publisher/community
leads. Duplicate Walmart IDs use the latest saved lookup. Other category views include matching
monitor products alongside Walmart. Use **Source** to narrow the list; retailer,
seller, condition and check time appear on every card. Complete desktops and loose
components remain in separate groups. Listings with the same ID in different
sources do not overwrite each other; exact duplicate source identities collapse.
Different retailer/seller offers remain separately comparable.

The browser rereads local results every 15 seconds without additional
retailer requests. The installed monitor retains its existing schedules, backoff and
notification rules, subject to the notification mode you select in Watching. HP and Reddit remain visible as unavailable until their
access actually recovers. Slickdeals/Reddit posts appear under **Reported deals**,
never as confirmed inventory. eBay variants, risky sellers, multi-item lots, and
missing shipping quotes remain held. Apple's current collector does not establish
shipping, so its finds remain visible outside the delivered-price ranking.

## Builder coverage

CyberPowerPC discovery reads the public prebuilt catalog; Skytech discovery reads
its published exact-SKU sitemap every six hours. Fixed RTX 5080/5090 products are
checked every ten minutes, subject to the existing host throttles, robots rules,
backoff and 48-product-per-retailer cap. Configurator/family URLs and configuration
query parameters are rejected. Only matching selected SKU, specifications, USD
price, condition and stock evidence can produce a current offer. Confirmed offers
use the existing alert preferences, exact-build history and comparable-price rules.
Unknown shipping or conflicting availability stays outside price comparisons.

iBUYPOWER's public RDY catalog is checked every fifteen minutes. On October 7,
2026, that catalog was readable but the tested individual product page returned
HTTP 403. These catalog quotes retain unknown condition/shipping and unconfirmed
availability; the sold-out list can establish an out-of-stock label. They cannot
produce stock alerts, delivered-price averages or historical price observations.

Live access checks on October 7, 2026 found B&H and Adorama denied requests with
HTTP 403. They have no enabled direct collectors. Best Buy remains deferred:
the earlier signup investigation found free-email/.edu restrictions and no API
key, and its published API terms separately restrict cached content to 72 hours.
Costco is omitted by user preference. Publisher reports may still mention any
of these retailers without establishing inventory.

Skytech can publish `InStock` and `in_stock=true` alongside zero
`quantity_available`. This disagreement stays unconfirmed, even with an enabled
Add to Cart button. Optional paid warranties and engraving are excluded from the
base configuration; hardware options require separate configuration review.

The October 7 live validation parsed all 31 discovered Skytech models: three had
consistent in-stock evidence, nine were out of stock and nineteen had incomplete
or conflicting stock signals. CyberPowerPC discovery found one qualifying 5080
prebuilt with agreeing price/specification/stock evidence. The saved iBUYPOWER
catalog supplied twelve 5080/5090 quotes, all kept unconfirmed. Publisher parsing
accepted 37 recent tech reports, including two explicitly attributed to Best Buy.
These counts are a dated integration check, not current purchase availability.

## Publisher deal reports and overlap

TechScout collects recent tech reports across retailers from the publishers' public
RSS feeds: Ben's Bargains (Amazon, desktops and memory), DealNews (computers and
recent deals), and 9to5Toys. A background worker checks the six feed URLs every
15 minutes while the dashboard server runs. Restarting respects the saved check
schedule. Browser polling and **Reload results** only read the local cache.
This uses no Amazon credentials or paid service and sends no alerts.
All reports appear in **All deals** and matching product categories. **Amazon
deals** remains restricted to reports explicitly attributed to Amazon. Structured
publisher retailer fields take precedence; ambiguous or missing attribution stays
unknown. Amazon links used for comparison cannot identify another retailer's offer.

Each source can inspect up to eight new or changed publisher articles per check,
respecting its robots rules. Structured product names and an unambiguous Amazon
product ID can improve matching. For 9to5Toys a single Amazon short link in the
article's first relevant paragraph may be resolved to its redirect destination;
Amazon product pages are never fetched. Other affiliate click trackers and forms
are not followed. Roundups and ambiguous multi-product links supply no product ID.

Matching reports become one card when they share an Amazon product ID or an exact
normalized product name and the same retailer. Title normalization removes the
trailing quoted-price clause but preserves configuration words. Conflicting known
ASINs, capacities, quantities, colors and conditions stay separate; generic names
and uncertain title similarities do not merge. Existing community posts can join
when they explicitly identify Amazon and match the exact product name. Direct
retailer inventory remains separately ranked and never inherits publisher prices.

A card preserves every report's original publisher URL, title, description,
quoted price, publication/check time and mentioned Prime/coupon/subscription
terms. Differing quotes display a range, with each quote still visible in
**Source reports**. Filtering by a publisher retains the complete combined card.
Saving the card uses one comparison slot; previous individual report selections
can resolve to that card. Extra reports do not create market averages or verify
retailer stock, seller, shipping, final price or a historical discount.

Feed entries expire from discovery after 72 hours. A feed check older than 30
minutes or a failed check labels its reports as needing another check. A current
report from one publisher cannot refresh another publisher's old quote. The
bounded public cache is `reports/deal-feeds.json`; it contains no credentials.
Original DealNews content and publisher/referral links are retained in source
reports, following its [published feed guidance](https://www.dealnews.com/pages/rss.html).

**Check Walmart now** runs only the selected
category's preset searches (10 results per search), then replaces its snapshot.
Opening the page, changing categories and checking refresh progress do not make
Walmart calls. Custom CLI searches remain available through the commands below;
the dashboard button always uses presets. One check runs at a time, with a
30-second pause between starts. Failed checks are recorded locally and do not
make an older snapshot look newly available. A check interrupted by server
shutdown also leaves its previous snapshot outside the current ranking.

## How the dashboard ranks

Exact-build price evidence is separate from notification qualification and budget
targets. Confirmed available complete-PC totals are retained for 90 days in
`prebuilt-observations.json` beside the monitor's existing price history, and in
`reports/walmart-prebuilt-observations.json` for explicit Walmart checks. Seller,
condition, published configuration and (for Walmart) ZIP changes start separate
evidence. Browser reads never add observations or make extra retailer requests.

Each UTC day contributes its last available total to the historical median;
today is excluded and at least three prior days are required. Each day's observed
range is also retained. Older monitor records captured only distinct prices, so
they contribute to the recorded range, never to the daily median. A first sighting
is labeled **Collecting exact-build history**. These are observed quotes with
gaps, not a continuous stock log or proof of an all-time low. Stale/sold-out cards
show saved evidence without claiming a current discount.

The separate peer rating matches exact GPU and CPU, RAM capacity and DDR type,
single SSD capacity, and condition. Only fresh, available offers with known totals
and no source-verification failures qualify. The target offer is excluded from
its own sample. Duplicate seller/model/configuration listings use their cheapest
available quote; missing model IDs collapse by seller and core configuration.
Ratings need at least three other offers from two sellers. Until then, matching
offers remain inspectable under **Price evidence & build details**, labeled
**Insufficient comparable offers**. This is the loaded source sample, not the
whole market; browser filters do not recalculate it.

**Below peer median** and **Above peer median** require at least a 5% difference;
otherwise the offer is **Near peer median**. The median, range, sample size,
sellers, timestamps and source links are disclosed. Confidence is moderate when
core specs match: PSU, motherboard, cooling, warranty and variable component
brands remain visible evidence, without guessed price premiums or a performance
score. Conflicting selected configurations, missing core specs and multiple-drive
configurations produce no peer rating. Budget targets and RAM reuse stay separate;
these price labels do not change notification thresholds or delivery receipts.

- Use independent **Product type**, **GPU**, **RAM**, **CPU**, **Storage**, **Condition**, and
  **Source** filters. For example, GPU **RTX 5090** includes every matching RAM
  capacity and condition; adding **64GB** narrows that selection. Filters without
  established values hide unless selected. Filter counts include all exact matches;
  source counts can overlap on cards with multiple publishers. Removable chips
  stay visible as you scroll. **Clear filters** restores all configurations.
  Each category remembers filters, budget, sorting, RAM-reuse preference and
  alternative visibility in this browser, including zero-result selections.
  Missing or ambiguous specs appear as **Not established**; GPU VRAM is not
  system RAM. These listing attributes do not establish compatibility or stock.
  Saved comparisons remain visible regardless of filters.
- Main rankings require availability from a recent retailer check,
  a positive price, known shipping, seller and condition, and a snapshot no older
  than 15 minutes for Walmart. Monitor freshness follows its collection interval
  plus 90 seconds (at least 15 minutes, at most 61.5 minutes for hourly Apple checks).
  A failed source or a monitor heartbeat older than 90 seconds holds its offers. Expired results move outside the ranking even if the page is
  left open; only a manual check retrieves new Walmart data. Each source expires
  independently, so a failed Walmart request cannot invalidate fresh Newegg results.
- **Current offers** shows exact filter matches with recent retailer evidence.
  It includes ordinary listings, not just recommended deals. Browse and compare
  cards put a prominent text-and-color assessment above the title: red **Skip**,
  amber **Watch / review**, gray **Value unassessed**, or green favorable evidence.
  Green requires a current qualifying component verdict or a whole-build price
  at least 5% below its matched-peer median; the latter is labeled **Below
  comparable prices**, not a build-quality recommendation. Whole-build history
  alone stays amber and a budget target alone cannot turn a card green. Stale or
  unverified rated offers require a new check. Availability remains a separate
  badge. Legacy complete PCs retain their system identity, use desktop facets,
  and show **Value unassessed** instead of a GPU-only verdict or price baseline.
  **Other matching products** follows automatically, including builds outside
  your RAM-reuse preference, missing details, unavailable items, stale offers,
  and unverified publisher reports. Each card labels its status; the header
  counts jump to their sections. Cards keep compact specs visible and move full
  titles, original group ranks and detailed evidence into **Listing details**.
  Explicit retailer unavailability is labeled **Out of stock** (or **Out of stock
  at last check** for an older result), with a **Saved price** note. Unknown
  availability stays unconfirmed. Price and stock check times, including the time
  zone, appear beside prices in both browsing and comparison cards. Walmart cards
  explain that checks run on demand; reloading saved results does not refresh stock.
- **Prioritize reusing my existing 64GB RAM kit** is enabled by default for
  Desktops and separate from the category. Turning it off can promote a fresh,
  otherwise verified off-plan build; it never promotes failed or stale checks,
  unknown totals or publisher reports. With it enabled, documented physical RAM
  layouts sort first, then price plus shipping. **Lowest known total** and
  **Newest checked** provide other orders within each section. Missing totals
  follow known totals, ordered by item price or highest publisher quote when
  available. Unlike models
  can differ in performance, warranty and value; mixed-kit stability is unverified.
- **Similar alternatives** appears expanded after matches, with a blue divider
  and the changed specification on each card. It relaxes at most one known facet,
  retaining budget, source and product type. It also considers existing monitor
  results from outside the selected category. Unknown replacement specs are not
  suggested. Six alternatives appear initially; **Show more alternatives** reveals
  the rest. **Hide alternatives** remembers your choice. Browsing this section
  does not run additional retailer searches.
- **Maximum price** uses known total where available, otherwise item price or the
  highest publisher quote. Unknown prices are excluded when a budget is set;
  unknown shipping can still add to the cost. Known tablet storage mismatches
  remain marked for verification. Source status distinguishes failed checks,
  stale monitor heartbeat, overdue checks and sources that are not enabled.
- Save up to three finalists in the browser. Their product IDs and shopping
  preferences are stored locally. If a saved ID disappears from loaded results, the page
  reports it as missing instead of displaying an old price.

The server binds only to `127.0.0.1`. It serves a fixed set of assets and a public
shopping-field projection, never arbitrary files or credential metadata. Refresh
requires the local page's token and matching origin; mismatched Host headers are
rejected. `dashboard-last-check.json` contains only the latest per-category check
status and time, with no prices or authentication data. Keep credentials in the
existing protected directory. The optional Windows shortcut setup starts the
local dashboard at sign-in.

The dashboard shares public results and watch preferences with the installed
alert monitor. The monitor remains responsible for notifications and price
history; the dashboard creates no additional monitoring tasks. Public feed
reports overwrite a bounded cache while the dashboard is running. It does not read
`.env` or `secrets.env`. The reports contain current API evidence, not fabricated
traffic or a claim that an application description grants additional rights.
Account access alone is not approval of downstream uses; the account holder
must keep actual use and application information aligned with applicable
[Walmart API terms](https://walmart.io/termsandcondition) and, where applicable,
[affiliate terms](https://affiliates.walmart.com/terms).

## Deals, Watching, Alerts and Sources

The blue dashboard has four views. **Deals** includes the alerter's existing
verdict, target, evidence and latest per-channel decision on assessed cards.
**Qualifying deals** and **Target price met** require both an eligible engine
judgment and current retailer evidence. Unassessed Walmart research and publisher
reports remain labeled. **Best deal verdict** sorts eligible judgments first
within each section. **New monitor finds · 24h** uses first sighting, preserved
across checks and restarts; it starts tracking with this upgrade.

**Watching** saves up to 40 exact searches or products, including GPU, RAM, CPU,
storage, condition, source, budget and the RAM-reuse preference. Edit or pause
individual watches here. The notification mode defaults to **All qualifying
deals**, preserving existing alerts. **Only enabled watches** narrows delivery
to matching watches; zero enabled watches means zero deal notifications.
**Pause deal notifications** suspends delivery while collection continues.
Health warnings are separate. Changes apply on the next monitor job, including
the next digest, and never relax the engine's deal or evidence requirements.
Alternative cards do not broaden a saved search's filters. Watches use existing
monitor coverage; they do not start new queries. Walmart and publisher-only
coverage remains browse-only. A malformed preferences file pauses deal delivery
until repaired; an absent file uses the existing all-deals default.

**Alerts** retains up to 500 successful sends and failed attempts, with event
prices and times. Sent means the transport accepted the notification. Existing
receipts seed history as products are assessed again; this is not a complete
historical inbox. **Why didn't this alert?** shows the latest per-channel decisions
for loaded monitor results, including unchanged, filtered, ineligible and failed.
**Open current card** opens its latest result; missing products retain their
original source link. **Sources** separates coverage and health from shopping.

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
are local personal data and are not committed. Confirmed available complete-PC
totals also update the separate bounded history described above; request receipts
are not appended to it.

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
- The standalone HTML research report's older item-price averages need at least two distinct, available offers with identified sellers,
  conditions and positive prices. Desktop cohorts match CPU, GPU, installed DDR5
  RAM capacity and SSD capacity; other components can differ. Other products require
  matching model, title, condition and returned attributes. These are selected
  sample means of current item prices before shipping/tax, not market averages
  or historical price baselines. Sparse or ambiguous specifications produce no
  average. Search coverage is shown explicitly. The dashboard uses the stricter
  delivered-total peer medians described above, separately from these report means.
- Desktop RAM checks reuse `config/desktop-profile.toml`: factory 32GB or 64GB,
  owned 2×32GB DDR5, four slots and a possible 96GB/128GB total. Off-plan systems
  are labeled. Missing layout evidence stays **NEEDS SPECS**. Even a documented
  physical fit does not verify mixed-kit stability or memory speed. No new kit
  purchase is added to the default desktop budget.

## Validation

```powershell
python -m pytest -q tests/test_techscout.py tests/test_techscout_dashboard.py
python -m pytest -q tests/test_deal_feeds.py tests/test_shopping_sources.py tests/test_shopping_integration.py
python -m pytest -q tests/test_builder_sources.py
python -m pytest -q tests/test_techscout_facets.py tests/test_techscout_browsing.py
node --test tests/techscout_browsing.test.cjs
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
