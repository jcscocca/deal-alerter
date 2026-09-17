# Deal alerter

Tells you when something you want is actually cheap, measured against its own
price history rather than the discount badge a store put on it.

It watches two very different markets:

| | Steam | Hardware |
|---|---|---|
| **Watches** | Games on your Steam wishlist | GPUs and unified-memory machines on your watchlist |
| **Evidence** | IsThereAnyDeal's full Steam price history | A price log this tool collects for itself |
| **Asks** | Is this the price to buy at? | Is it cheap, is it good value, does it help *you*? |
| **Verdicts** | `WAIT` up to `ALL_TIME_LOW` | `PASS` up to `GRAIL` |
| **Tells you** | Daily email | Hourly push, daily email digest |

Both run through one core, `dealcore/`: fetch, judge, deduplicate, notify, save
state. Judgment never crosses over. The two verdict ladders are separate enums
that the core refuses to compare, because a Steam band must never satisfy a
hardware threshold.

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

## Hardware: cheap, good value, and useful to you?

A listing says "$749" without saying whether that is good for a 3090, whether it
is really a 3090, or whether 24GB changes anything about what your machines can
run. There is no IsThereAnyDeal for GPUs. For each listing that matches a hunt:

| Question | How |
|---|---|
| **Is it cheap?** | Percentile against every price logged for that exact part and condition, cross-checked against a sold-price reference |
| **Is it good value?** | $/GB of VRAM, and $/GB-TB/s -- capacity times bandwidth -- against its class |
| **Does it help *you*?** | What it changes about the largest model your machines can hold (`rig.py`) |

The third question is the point. A cheap card that does not grow the memory pool
is capped below the alert floor however cheap it gets.

### The price log

Nothing like ITAD exists for hardware, so the tool logs what it sees to
`state/hardware/US/prices.jsonl` and grows its own answer.

- **Until a part has 8 observations spanning 14 days,** it is judged against the
  catalog's reference price, labelled provisional, and capped at `EXCEPTIONAL`.
  Where that reference is an estimate rather than a sold average the cap is
  `STRONG`: it can reach the digest, never your phone.
- **Used, refurbished and new never pool.** Once a part has enough confirmed
  sales, those replace asking prices as what it is judged against.
- **One listing gets one vote.** A listing seen every hour for a month is one
  observation. A price change on it is another, because that is information.
- **Being shown and being recorded are separate bars.** Prebuilts, bundles,
  for-parts cards, bait-priced listings, untrusted sellers and eBay's
  price-sorted search results are shown to you with the reason, and kept out of
  the log. `docs/hardware-judgment.md` has the real listings behind each rule.

`--stats` shows what the log knows so far.

### Hunts

`config/watchlist.toml` is what to hunt. A hunt is a rule, not a SKU list -- you
want any 24GB Ampere card under $700, whoever is selling:

```toml
[[hunt]]
name = "RTX 3090 (pair up)"
parts = ["rtx_3090", "rtx_3090_ti"]
target = 700.0
quantity_wanted = 2
```

At or under `target` you are alerted whatever the history says. A part with no
hunt is matched and then never judged. Specs and reference prices live in
`alerters/hardware/native/catalog.py`; used-market references decay, so retune
them against sold data now and then. Your machines live in `rig.py`.

### Beyond search results

- **Listings you found yourself.** `--add URL --price 640 --title "..."` records
  one in `state/hardware/US/manual.jsonl` and says immediately whether the title
  matched a part and a hunt. The URL is stored, never fetched, and `--sold`
  records a sale you witnessed. Manual entries do not age out: delete the line to
  delete the entry. Commit and push the file, or the scheduled runs never see it.
- **Prebuilts asking less than the card inside them** are flagged in the report.
  An asking-price gap is not profit; neither side has sold.
- **Not only NVIDIA.** AMD pro cards, the 7900 XTX, the Arc Pro B60, older Mac
  Studio Ultras and 64GB unified boxes are in the catalog as reference estimates.

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

`.github/workflows/check.yml` runs on GitHub Actions and commits state back to
the repository. Each schedule has its own repository variable, so each can go
live as soon as its secrets exist:

| Schedule (UTC) | Runs | Switch | Needs |
|---|---|---|---|
| 18:15 daily | Steam | `ENABLE_STEAM` | `STEAM_ID`, `ITAD_API_KEY`, SMTP |
| 02:47 daily | Hardware digest | `ENABLE_HARDWARE` | SMTP, and eBay keys unless you can do without eBay |
| :37 past, 14:00-06:00 | Hardware push | `ENABLE_HARDWARE_FAST` | `NTFY_TOPIC` or `DISCORD_WEBHOOK` |

```bash
gh variable set ENABLE_STEAM --body true
```

Steam runs just after Steam's 10:00 PT price flip. The push window is 7am to
11pm Pacific because of Actions minutes: a hardware run bills about three, so
hourly around the clock would pass the Free plan's 2,000 a month for a private
repository, and when the quota runs out every workflow stops until the next
cycle. With more minutes to spend, the comment in `check.yml` says what to change.

To try a run by hand: Actions, Check deals, Run workflow. It defaults to a dry
run and keeps the HTML preview as a downloadable artifact.

Tests do not run before alerts. `tests.yml` gates code on pushes and pull
requests instead, so a broken test cannot silence an alert.

**Scheduled runs are best effort, and GitHub means it.** Measured 2026-09-17:
the hourly push loop produced one run in the eight slots between 14:00 and
21:00 UTC, the daily hardware digest arrived five hours after its slot, and
Steam arrived three. Under an earlier 15-minute schedule GitHub created about
eight runs a day out of ninety-six. So the push loop is not hourly in practice,
the Actions-minute arithmetic above is a ceiling rather than a forecast, and
anything that has to reach you within the hour needs a trigger from outside
GitHub.

**Keep one writer.** Don't make real, non-dry local runs while the schedules are
on: two writers committing the price log and alert receipts will conflict, and
the workflow fails on a push conflict rather than force-pushing. GitHub also
disables schedules after 60 days without repository activity. The state commits
count, and GitHub emails before it disables anything.

## State and failure

Everything durable is committed JSON under `state/`, split by domain and
country so one market's price never becomes another's baseline:

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
