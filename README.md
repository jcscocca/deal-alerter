# Deal alerter: one workflow, two kinds of judgment

Python 3.11+. Steam compares a game with its own price history. Hardware compares
price, value and usable capability. They share execution mechanics, not a verdict
vocabulary or a configurable rule interpreter.

The Steam plugin is complete, including live API transport and an offline demo.
The hardware adapter is complete, but its native domain bodies are intentionally
imported from your existing checkout: the supplied context bundle included only
their signatures. This distribution does not contain a guessed matcher or catalog.

## Install and run Steam

From this repository's root:

    python3.11 -m venv .venv
    . .venv/bin/activate
    python -m pip install -r requirements.txt
    python -m alerters steam --demo --all

The demo uses `examples/steam.json`, a synthetic API transcript, writes
`report-steam.html`, sends nothing and writes no persistent state. `--fixture`
also always implies a dry run. Neither option needs credentials or network access.

Copy `.env.example` to `.env`, then supply `STEAM_ID` and `ITAD_API_KEY` for live
reads. Supply `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_TO` for real email. A numeric
SteamID64, vanity name or Steam community profile URL is accepted. A public
wishlist is required; a missing/private response is reported, not treated as an
empty wishlist. Optional SMTP host, port and sender are environment variables.
Existing environment settings override `.env`.

    cp .env.example .env
    python -m alerters steam --dry-run --all
    python -m alerters steam --quiet-when-empty

Edit `config/steam.toml` for country, history window and thresholds. Optional
per-game targets go in `config/steam-targets.json`, using string appids as keys.
The six native bands and their ordering are unchanged. A target can make an
otherwise lower-band game eligible without changing its native verdict.

To retain prior Steam suppression and metadata, with the old cron stopped:

    mkdir -p state/steam/US
    cp ../steam-deal-alerter/state/alerts.json state/steam/US/alerts.json
    cp ../steam-deal-alerter/cache/games.json state/steam/US/games.json
    cp ../steam-deal-alerter/targets.json config/steam-targets.json
    cp ../steam-deal-alerter/config.toml config/steam.toml

Copy only files that exist. Use the configured country instead of `US` where
appropriate. The loader migrates legacy alert keys and receipts on the next real
save, without resetting suppression.

## Import and run hardware

First finish the old process's normal JSONL export and stop its cron. Then:

    python scripts/import_hardware.py ../ai-deal-alerter
    python -m pip install -r alerters/hardware/native/requirements.txt
    cp ../ai-deal-alerter/config.toml config/hardware.toml
    cp ../ai-deal-alerter/watchlist.toml config/watchlist.toml
    mkdir -p state/hardware/US
    cp ../ai-deal-alerter/state/alerts.json state/hardware/US/alerts.json
    cp ../ai-deal-alerter/state/prices.jsonl state/hardware/US/prices.jsonl
    python -m alerters hardware --dry-run --all
    python -m alerters hardware --fast
    python -m alerters hardware --digest
    python -m alerters hardware --stats

The original catalog anchors are USD, so the hardware adapter refuses non-US
configuration rather than comparing different currencies as dollars. Keep the
existing eBay/Reddit credentials in environment variables. `--fast` needs at
least one of ntfy, Discord or desktop notification, but no SMTP credentials.
`--digest` needs SMTP but not a push transport. A run without either flag performs
both. `--stats` does not need notification credentials or modify persistent files.

Set `NTFY_TOPIC` to your private topic, `NTFY_TOKEN` when applicable, and optionally
`NTFY_SERVER`. Set `DISCORD_WEBHOOK` for Discord. Native macOS notification uses
terminal-notifier when available and osascript otherwise; `DESKTOP_NOTIFY=1`
explicitly enables it. Source-provided titles are passed as arguments, not code,
and only HTTP(S) listing URLs can be opened.

See `MIGRATION.md` for every module's destination, preserved safeguards, deliberate
behavior changes and the limits of verification with signature-only inputs.

## Tests and compatibility

    python -m unittest discover -s tests -v
    LEGACY_STEAM_VERDICT=../steam-deal-alerter/sda/verdict.py python -m unittest tests.test_equivalence -v

During construction, all 36 test methods passed on Python 3.13.5, including
direct comparison with the supplied original. All files also parse under Python
3.11 grammar; the included CI workflow executes the suite on Python 3.11.

The default suite includes a 28-row Steam equivalence table, checking native
bands and SHA-256 hashes of the entire serialized assessment, including exact
explanations, history statistics and targets. Those expected hashes were generated
from the supplied original `sda/verdict.py`. The optional environment variable
also executes your original function alongside the port. A fixed clock tests the
evolved Steam `_ago()` phrasing, including year-rounding boundaries.

Other tests cover cent-versus-4% re-alerting, strict reminder boundaries, legacy
state migration, collapsed variation IDs, partial-source retention, failed-send
retries, per-transport baselines, cohort-before-append ordering, observation vetoes,
mode-specific secrets, safe rendering, API batching and an end-to-end offline CLI
run. Hardware adapter tests use explicit test doubles; they do not claim to test
the omitted real matcher or observation engine.

The original zero-history-low exception and recent-ended-sale episode quirk are
covered rather than silently changed. Compatibility is about the original's
actual behavior, not a more attractive rewrite of its comments.

## State and failure semantics

Steam delegates evidence reads to ITAD; it never fabricates a local price log.
Hardware rebuilds temporary SQLite from committed JSONL, judges the entire run
against the pre-run evidence, then appends only approved observations. Daily runs
retain 730 days; fast runs do not prune. `loggable` and `multi_variant` are carried
unchanged and source vetoes cannot be overridden downstream.

State is separate by domain and country. Only a complete source enumeration may
remove missing alert keys. Capped hardware searches are not complete inventories.
Failed history reads preserve raw live identities and do not masquerade as ended
sales. Corrupt state fails loudly instead of resetting into a notification storm.

Only successful transports earn receipts. Email and each push transport retain
independent price/verdict baselines. A dead transport does not prevent the other
channels or sources from doing useful work; the command still exits nonzero so
monitoring can see degraded operation. Successful receipts and evidence are saved
even when another delivery fails.

This is not an exactly-once delivery system. A remote service can accept a send
and then lose the response, or a process can fail between delivery and saving the
receipt. A retry may duplicate that notification. Atomic local writes and
immediate per-channel receipts reduce that window without pretending to close it.
Partial SMTP recipient refusal also retries the digest, potentially repeating it
to recipients who already accepted it.

Do not run simultaneous local writers against one state directory, or a local
writer and CI against divergent copies. The workflow serializes repository state
writers, but local processes have no distributed lock. Stop the old cron during
migration; choose one authoritative writer or separate state directories.

## CI

The workflow is installed but scheduled runs are gated by repository variables:
set `ENABLE_STEAM=true` after configuring Steam secrets, and
`ENABLE_HARDWARE=true` after importing and committing the native hardware files,
watchlist, state and required secrets. Manual dispatch defaults to a dry run.
Steam accepts digest mode only; hardware accepts digest or fast mode.

The schedules are 02:17 UTC for Steam, 02:47 UTC for the hardware digest, and
minutes 7/22/37/52 each hour for fast hardware checks. Scheduled execution is not
a delivery-time guarantee. Both domains use one concurrency group because both
commit to the same branch. The final step runs even after a partial failure and
stages only JSON/JSONL under `state/`, never `.env`, HTML or SQLite. Rebase/push
conflicts fail visibly; the workflow never force-pushes. Branch rules must permit
the bot's normal state commits.

The new Steam transport uses the documented ITAD API key header, shop-ID lookup,
prices v3, store-low v2, history v2 and info v2 interfaces. Its network contract was
checked against the official documentation; authenticated live requests were not
performed during creation of this repository. The bundled transcript is synthetic,
not a recording of current game prices.

API reference: https://docs.isthereanydeal.com/
Action references: https://github.com/actions/checkout and https://github.com/actions/setup-python
