# Deal alerter

Find unusually good deals on computer parts and monitors, with optional watches
for products you want. Steam wishlist alerts continue as a separate lane.

| | TechScout / hardware | Steam |
|---|---|---|
| **Focus** | Standout component and monitor deals, plus useful peripherals | Games on your Steam wishlist |
| **Evidence** | Exact-part history and dated model-specific references where supported | IsThereAnyDeal's Steam price history |
| **Browse** | Local dashboard with product filters, saved comparisons and source status | Daily report |
| **Notify** | Qualifying monitored offers through push and daily email | Daily email |

Complete computers, laptops and tablets are outside the hardware shopping scope.
The completed desktop no longer drives a buying project: prebuilt tracking,
whole-build comparisons, RAM completion and owned-kit reuse preferences are
retired from the active experience. RAM capacity and type remain useful filters
for buying individual memory kits.

## Steam: is this the price to buy at?

Steam tells you a wishlisted game is 40% off. It does not tell you whether 40%
is good *for that game*. Every discounted wishlist game gets one of six verdicts
from its current price measured against its full price log:

| Verdict | Meaning |
| --- | --- |
| `ALL_TIME_LOW` | At or below the cheapest Steam has ever sold it |
| `MATCHES_LOW` | Within 2% of the record low -- waiting saves you pennies |
| `NEAR_LOW` | Within 10% of the record low |
| `BEST_THIS_YEAR` | Lowest in 12 months, but it has gone deeper before |
| `DECENT` | 50%+ off, though history says better exists |
| `WAIT` | Shallow relative to what this game reliably reaches |

You are emailed at `NEAR_LOW` and above; everything else goes in a compact
"history says wait" table. Two details keep the verdicts honest:

- **Sale episodes, not price rows.** ITAD logs several rows during one sale.
  Counting rows would claim a game goes on sale twelve times a year when it goes
  on sale twice.
- **A first-ever discount is never called an all-time low.** For a new release,
  today's price is trivially the lowest ever recorded, so it is reported as
  having no history to judge against instead.

`config/steam-targets.json` sets per-game ceilings, keyed by the appid in the
store URL. A game at or under its target always emails you, whatever the
history says.

Why email: there is no API for notifying your own Steam account, and a bot
account that friend-messages you breaks the subscriber agreement and trips Steam
Guard from every fresh CI runner. Email is boring and it works.

## Hardware: standout parts and monitor deals

Start the local dashboard:

```bash
python -m alerters.techscout --serve
```

Open [TechScout on this computer](http://127.0.0.1:8768/). The home feed puts
qualifying, current component and monitor deals first. Ordinary offers and
publisher/community reports stay available to browse with their evidence and
verification status. A low price alone is not a recommendation.

- **Price evidence stays specific.** Component verdicts use the exact part and
  condition, with historical observations or a dated reference. Monitor alerts
  require a benchmark for that exact model. Generic retail list prices and
  publisher discount badges do not establish a standout deal.
- **Offer checks remain separate.** Seller risk, selected variant, condition,
  shipping, stock and freshness can hold a tempting listing out of recommendations
  and alerts. New, used and refurbished prices do not pool.
- **Your interests can narrow delivery.** Watching saves product searches and
  price targets using existing monitor coverage. A watch does not start a new
  retailer query or make an unassessed product alertable. Parts without supported
  price evidence remain research candidates.
- **The completed rig is no longer a gate.** Individual parts can be interesting
  without increasing its memory capacity. Hardware inventory can remain a
  historical reference without restricting the discovery feed.

The catalog and enabled hunts define assessed component coverage; the broader
feed can also discover CPUs, storage, motherboards, memory and peripherals that
have no automatic verdict yet. The monitor's
[4K display watch](docs/4k-monitor-watch.md) still has its own explicit display
and exact-model benchmark requirements. Browser filters do not broaden that
collector or its alert criteria.

Public publisher feeds provide leads across retailers and never establish stock,
seller, shipping or checkout price. On-demand Walmart checks use a selected ZIP
and create browse-only research snapshots for **parts**, **monitors**, **memory**
and **supplies**. They do not send alerts or write whole-PC history. See
[TechScout setup, evidence and limits](docs/techscout-shopping.md).

The hardware price log records eligible observations at
`state/hardware/US/prices.jsonl` (or the installed runtime's equivalent). A part
needs at least 8 observations spanning 14 days before its own history can rank
it. Earlier assessments use supported references and remain provisional;
unverified or stale references cannot produce buy recommendations. `--stats`
shows the collected coverage. Manual component listings can be added with
`--add URL --price 640 --title "..."`; the URL is stored without being fetched.
`--sold` records a witnessed sale. See
[hardware judgment](docs/hardware-judgment.md) for the underlying evidence rules.

Repository changes must go through the existing
[ThinkPad Prepare/Update procedure](docs/thinkpad-monitor.md) to reach the installed
monitor and shortcuts. Editing or testing this checkout does not deploy it.
Legacy prebuilt/profile modules, saved history and dated investigation documents
remain for reference; they do not define the active shopping scope.

## Running it

Python 3.11 or newer.

```bash
python -m pip install -r requirements.txt
python -m alerters steam --demo --all      # sample report from a synthetic transcript: no keys, no network
```

Copy `.env.example` to `.env` for local runs. Variables already in the
environment win over the file.

```bash
python -m alerters steam --dry-run --all   # live data; writes report-steam.html, sends nothing
python -m alerters hardware --dry-run      # live data; writes report-hardware.html, sends nothing
python -m alerters hardware --stats        # what the price log knows
python -m alerters hardware --fast         # push only
python -m alerters hardware --digest       # email only
```

`--dry-run` records nothing, because "just checking" should not rewrite the
history every future verdict is measured against. `--force` ignores alert
history, `--all` adds the below-threshold table, and `--quiet-when-empty` skips
an email with nothing in it. Steam runs in digest mode only.

### Settings

| Setting | For | Notes |
|---|---|---|
| `STEAM_ID` | Steam | SteamID64, vanity name or profile URL. The wishlist must be readable: Privacy Settings, Game details, Public |
| `ITAD_API_KEY` | Steam | Free and instant at isthereanydeal.com/apps |
| `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO` | Any email | For Gmail, an app password, which needs 2-Step Verification. `MAIL_FROM`, `SMTP_HOST` and `SMTP_PORT` are optional |
| `NTFY_TOPIC` | Hardware push | `--fast` needs this, `DISCORD_WEBHOOK`, or desktop notifications on a Mac. Anyone who knows the topic can read your alerts, so pick an unguessable one and keep it secret |
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | eBay | Without them eBay sits out, and most of the used market with it |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | Faster Reddit | Optional. Reddit falls back to anonymous RSS, which works but is throttled hard. Reddit has stopped issuing new credentials; don't borrow another app's |

Tunables are in `config/steam.toml` and `config/hardware.toml`.

## Scheduling

Hardware monitoring moved
to the ThinkPad on October 4, 2026. `HARDWARE_WRITER=thinkpad` blocks GitHub
hardware runs, and both GitHub hardware switches are disabled. The external
dispatch jobs described below are an inactive alternative; do not enable them
while the local monitor owns hardware state. See
[ThinkPad monitoring](docs/thinkpad-monitor.md) for the active setup.

For fast local hardware checks, prepare the Windows startup and watchdog tasks
using [the ThinkPad cutover procedure](docs/thinkpad-monitor.md). Preparation and
dry runs do not activate anything. Cutover closes both GitHub hardware gates,
drains existing runs and transfers current hardware state; Steam stays on Actions.

`.github/workflows/check.yml` runs on GitHub Actions and commits state back to
the repository. Steam's daily check remains on GitHub. Its optional hardware
digest and external dispatch support remain available for a future change of
writer; they are inactive while the ThinkPad owns hardware state:

| Schedule (UTC) | Runs | Switch | Needs |
|---|---|---|---|
| 18:22 daily | Steam | `ENABLE_STEAM` | `STEAM_ID`, `ITAD_API_KEY`, SMTP |
| 02:52 daily | Hardware digest | `ENABLE_HARDWARE` | SMTP, and eBay keys unless you can do without eBay |
| :00, :15, :30, :45 | Hardware push: eBay and Slickdeals | External scheduler | `NTFY_TOPIC` or `DISCORD_WEBHOOK` |
| Every 5 minutes, from :01 | Hardware push: r/buildapcsales | External scheduler | `NTFY_TOPIC` or `DISCORD_WEBHOOK` |

```bash
gh variable set ENABLE_STEAM --body true
```

Steam runs just after Steam's 10:00 PT price flip. The external-dispatch
alternative below would run around the clock. Its limit is
eBay's instead: 5,000 Browse calls a day, and a run makes one per search query
(24), so eBay cannot go below every 10 minutes and stays at 15. Slickdeals
stays with it, since each run reads a feed per query. Reddit is one feed, so it
gets its own 5-minute loop; `HARDWARE_SOURCES` (a comma-separated list, also a
Run workflow input) is what splits them.
Reddit keeps the selected default scope, r/buildapcsales; the swap boards stay
excluded. An explicit `REDDIT_SUBS` environment setting can select another scope
without a scheduled workflow overriding it.

To try a run by hand: Actions, Check deals, Run workflow. It defaults to a dry
run and keeps the HTML preview as a downloadable artifact.

Tests do not run before alerts. `tests.yml` gates code on pushes and pull
requests instead, so a broken test cannot silence an alert.

**Scheduled runs are best effort, and GitHub means it.** Measured 2026-09-17:
the hourly push loop produced one run in the eight slots between 14:00 and
21:00 UTC, the daily hardware digest arrived five hours after its slot, and
Steam arrived three. Under an earlier 15-minute schedule GitHub created about
eight runs a day out of ninety-six. So the push loop is not hourly in practice,
the schedule above is a ceiling rather than a forecast, and
anything that has to reach you within the hour needs a trigger from outside
GitHub. Measured again 2026-09-26 to 28: 10-15 scheduled runs a day out of ~122.

### Optional external dispatch after transferring hardware ownership

If a reviewed rollback transfers hardware ownership away from the ThinkPad,
two jobs on an external scheduler can each `POST` to
`https://api.github.com/repos/jcscocca/deal-alerter/actions/workflows/check.yml/dispatches`
with headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`
and `X-GitHub-Api-Version: 2022-11-28`:

| Minutes | Body |
|---|---|
| `0,15,30,45` | `{"ref":"main","inputs":{"domain":"hardware","mode":"fast","dry_run":"false","sources":"ebay,slickdeals"}}` |
| `1-56/5` | `{"ref":"main","inputs":{"domain":"hardware","mode":"fast","dry_run":"false","sources":"reddit"}}` |

A success is `204 No Content`. The token is a fine-grained personal access
token for this repository only, with Actions: Read and write and nothing else.
It belongs in the scheduler, never in this repository. Pausing those jobs would
pause that alternative push loop. `HARDWARE_WRITER=thinkpad` still blocks real
hardware dispatches while the local runtime owns state.

Keep the minutes off 22 and 52 (0 and 1 mod 5 are): a dispatch arriving while a
daily is pending cancels the daily.

**Keep one writer.** Don't make real, non-dry local runs while the schedules are
on: two writers committing the price log and alert receipts will conflict, and
the workflow fails on a push conflict rather than force-pushing. GitHub also
disables schedules after 60 days without repository activity. The state commits
count, and GitHub emails before it disables anything.

## State and failure

Steam's live state is committed JSON under `state/`. After the ThinkPad cutover,
live hardware state is under `C:\ProgramData\DealAlerter\state`; the Git hardware
files are a recovery copy. Each domain/country keeps separate baselines:

```
state/steam/US/alerts.json       alert receipts
state/steam/US/games.json        title and box-art cache
state/hardware/US/alerts.json    alert receipts
state/hardware/US/prices.jsonl   the price log
state/hardware/US/manual.jsonl   listings added by hand
```

The hardware SQLite database is rebuilt from `prices.jsonl` in a temporary
directory on every run and never committed.

- **One dead source does not stop the run.** The run still exits nonzero so the
  failure is visible.
- **Only a complete enumeration removes an alert key.** A capped search that no
  longer returns a listing has not proved it is gone.
- **Each transport keeps its own receipts,** earned only by a successful send. A
  push that went through is not evidence the email did.
- **Corrupt state fails loudly** instead of resetting into a storm of repeats.
- **This is not exactly-once delivery.** A crash between sending and saving the
  receipt can repeat a notification.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

`tests/test_equivalence.py` pins the Steam judgment to the original
`steam-deal-alerter` with a golden table. Set `LEGACY_STEAM_VERDICT` to a
checkout's `sda/verdict.py` to compare against the original function directly.

## Layout

```
dealcore/          shared run loop: contracts, run, state, notify, report, config
alerters/
  __main__.py      the CLI: python -m alerters {steam,hardware}
  steam/           wishlist and ITAD transport, judgment, plugin
  hardware/        plugin adapter, alert identity, manual listings
    native/        matcher, catalog, rig, price log, verdict, sources
config/            tunables, Steam targets, hardware watchlist
state/             committed alert receipts and price log
docs/              how hardware judges, and why the port stops where it does
```

## History

This repository replaced `steam-deal-alerter` and `ai-deal-alerter`. Steam is a
full port, verified equivalent to the original. Hardware's domain modules are
vendored under `alerters/hardware/native/` rather than rewritten, since nothing
in them duplicates the core, and their test suite came across intact.
`MIGRATION.md` records where every module went, and
`docs/hardware-port-scope.md` records why the hardware port stops where it does.
