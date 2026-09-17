# Next steps: finish the cutover

Written 2026-09-16 on the Windows machine, for picking up on the Mac. Work
through the sections in order, and delete this file when section 5 is done.

Secret values must never appear in the conversation, because the transcript
persists. A Claude session may run commands that move them blind, such as
the grep-to-`gh secret set` pipeline below, but any command that needs a value
typed or pasted is yours to run.

## Where things stand

- **Merged** ([#1](https://github.com/jcscocca/deal-alerter/pull/1)): tests run
  in `tests.yml` and pass at 681 on Python 3.11 and 3.14, scheduled runs in
  `check.yml` only check deals, the four quarantined hardware tests are
  restored, and the README describes the product.
- **Everything is switched on as of 2026-09-16.** `ENABLE_STEAM`,
  `ENABLE_HARDWARE` and `ENABLE_HARDWARE_FAST` are all true. The old Steam
  workflow is disabled and the old launchd agents are unloaded.
- **Steam is on.** With the corrected `ITAD_API_KEY`, a dry run assessed the 2
  discounted games of 20 wishlisted with no problems and nothing new to send,
  because the old alerter already sent both on Sep 14. The first real run is
  18:15 UTC.
- **Hardware is on and has run.** The first scheduled push loop and digest ran
  on 2026-09-17, sent 2 pushes and a 19-deal email, and grew the price log
  from 1,620 to 2,065 observations.
- The old repos moved to the `jcscoccaprivate` account. The old `jcscocca/...`
  URLs redirect, but `gh repo list jcscocca` does not show them.

## 0. Get this repo on the Mac

```bash
gh repo clone jcscocca/deal-alerter ~/Repos/deal-alerter
cd ~/Repos/deal-alerter
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

If it is already cloned, `git pull` instead. Commands below run from
`~/Repos/deal-alerter` unless they say otherwise.

## 1. The old hardware alerter on the Mac -- do this first

**Done 2026-09-16 on the Mac.** Both agents were still loaded but had failed
every run since 2026-08-19 because `~/Repos/ai-deal-alerter/.venv` no longer
exists (digest exits 127 daily at 09:00, fast exits 78 every 15 min). They are
now booted out, with their plists in `~/Library/LaunchAgents.disabled/`. The
Mac's log had 203 rows newer than the committed one and none missing, and no
changes outside `state/`; both files are copied into `state/hardware/US/`, and
stats and the 681 tests pass.

It ran from `~/Repos/ai-deal-alerter` under two launchd agents,
`com.jscocca.ai-deal-alerter.fast` and `com.jscocca.ai-deal-alerter.digest`.

**Why did it stop?**

```bash
launchctl list | grep ai-deal-alerter
tail -n 40 ~/Library/Logs/ai-deal-alerter/*
```

**Stop the agents for good**, keeping the plists in case. Do this before the
data check below, so nothing rewrites the log while you compare it:

```bash
launchctl bootout gui/$(id -u)/com.jscocca.ai-deal-alerter.fast
launchctl bootout gui/$(id -u)/com.jscocca.ai-deal-alerter.digest
mkdir -p ~/Library/LaunchAgents.disabled
mv ~/Library/LaunchAgents/com.jscocca.ai-deal-alerter.*.plist ~/Library/LaunchAgents.disabled/
```

**Is there price data that never reached GitHub?** `bin/run-digest.sh` only
commits on `main`, and a failed push leaves the commit local.

```bash
git -C ~/Repos/ai-deal-alerter fetch
git -C ~/Repos/ai-deal-alerter status
git -C ~/Repos/ai-deal-alerter log --oneline origin/main..HEAD
```

Then compare the Mac's log with the committed one. Rows are unique on
source, listing and price:

```bash
python3 - state/hardware/US/prices.jsonl ~/Repos/ai-deal-alerter/state/prices.jsonl <<'EOF'
import json, sys
def load(path):
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return {(r["source"], r["listing_id"], r["unit_price"]): r for r in rows}
committed, mac = load(sys.argv[1]), load(sys.argv[2])
latest = lambda rows: max((r["last_seen"] for r in rows.values()), default="-")
print(f"committed: {len(committed)} rows, last seen {latest(committed)}")
print(f"mac:       {len(mac)} rows, last seen {latest(mac)}")
print(f"only in committed: {len(committed.keys() - mac.keys())}   only on mac: {len(mac.keys() - committed.keys())}")
EOF
```

- **"only on mac" above 0 and "only in committed" at 0:** the Mac has newer
  data and loses nothing. Bring it across before `ENABLE_HARDWARE` is set, so
  no scheduled run writes the log first:

  ```bash
  cp ~/Repos/ai-deal-alerter/state/prices.jsonl state/hardware/US/prices.jsonl
  cp ~/Repos/ai-deal-alerter/state/alerts.json state/hardware/US/alerts.json
  .venv/bin/python -m alerters hardware --stats
  .venv/bin/python -m pytest -q
  ```

  Commit to `main` and push.
- **"only in committed" above 0:** rows were removed on the Mac (the log has
  been purged before). Look at what is missing before copying anything.
- **Changes outside `state/` in that checkout:** stop. Code that never left the
  Mac has to be ported into `alerters/hardware/native/` before the old repo is
  archived.

## 2. Secrets

**Done 2026-09-16.** The command below set `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_TO`, `NTFY_TOPIC`,
`EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET`. The old `.env` names `NTFY_TOKEN`,
`DISCORD_WEBHOOK` and both Reddit keys but leaves them blank, so those stay
unset. Its `SMTP_HOST`, `SMTP_PORT` and `NTFY_SERVER` match the workflow
defaults, so no repository variables are needed.

The Mac's old `.env` has what the Windows one lacked. This sends only the
settings that have a value, and prints none:

```bash
grep -E '^(SMTP_USER|SMTP_PASSWORD|MAIL_FROM|MAIL_TO|NTFY_TOPIC|NTFY_TOKEN|DISCORD_WEBHOOK|EBAY_CLIENT_ID|EBAY_CLIENT_SECRET|REDDIT_CLIENT_ID|REDDIT_CLIENT_SECRET)=.+' ~/Repos/ai-deal-alerter/.env | gh secret set -f - -R jcscocca/deal-alerter
```

The IsThereAnyDeal key is shown at isthereanydeal.com/apps/my. That page also
shows OAuth client credentials, and this needs the API key. Copy it, then run
this. It checks the clipboard's key against ITAD and stores it only if ITAD
accepts it, and it avoids `gh`'s interactive prompt, which a terminal's escape
replies can break:

```bash
printf 'ITAD-API-Key: %s' "$(pbpaste | tr -d '[:space:]')" | curl -s --fail-with-body -X POST 'https://api.isthereanydeal.com/games/prices/v3?country=US&shops=61' -H @- -H 'Content-Type: application/json' -d '["018d937f-12e9-71ca-a5d5-f31985870694"]' && echo && pbpaste | tr -d '[:space:]' | gh secret set ITAD_API_KEY -R jcscocca/deal-alerter
```

A rejected key prints ITAD's `Invalid or expired api key` and stores nothing.

```bash
gh secret list -R jcscocca/deal-alerter
```

One `MAIL_TO` now serves both domains; comma-separate several addresses. If
the mail server is not Gmail on port 587, also set the repository variables
`SMTP_HOST` and `SMTP_PORT`.

## 3. Steam cutover -- in this order

**Done 2026-09-16.** The old workflow is disabled, its state as of its Sep 16
run is committed, and `ENABLE_STEAM` is on. The first dry run failed with a
bare `HTTP 403` because an OAuth client credential had been stored as the key.
[#2](https://github.com/jcscocca/deal-alerter/pull/2) puts ITAD's reason and a
hint about that mix-up back into the error. With the API key stored, the dry
run assessed 2 games with 0 problems and "No new recommendations".

Needs `ITAD_API_KEY`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_TO`.

**Stop the old workflow first**, and make sure no run is still going:

```bash
gh workflow disable check-deals.yml -R jcscoccaprivate/steam-deal-alerter
gh run list -R jcscoccaprivate/steam-deal-alerter --limit 1
```

**Copy its latest alert state.** The copy taken on Sep 6 predates the alerts it
sent on Sep 14 (RimWorld among them) and would send them again. Config and
targets were checked identical and need nothing.

```bash
gh api -H "Accept: application/vnd.github.raw+json" repos/jcscoccaprivate/steam-deal-alerter/contents/state/alerts.json > state/steam/US/alerts.json
gh api -H "Accept: application/vnd.github.raw+json" repos/jcscoccaprivate/steam-deal-alerter/contents/cache/games.json > state/steam/US/games.json
```

Commit to `main` and push. **Then turn it on and dry-run it:**

```bash
gh variable set ENABLE_STEAM --body true -R jcscocca/deal-alerter
gh workflow run check.yml -R jcscocca/deal-alerter -f domain=steam -f mode=digest -f dry_run=true
```

The Check step should end with `N assessed; 0 problem(s).`, and the HTML
preview is attached to the run. The first real run is the next 18:15 UTC.

## 4. Hardware

**Switched on 2026-09-16.** Dry runs with eBay:

| Mode   | Assessed | Problems | Job time |
|--------|----------|----------|----------|
| digest | 608      | 0        | 114 s    |
| fast   | 605      | 0        | 112 s    |

Each bills 2 minutes, but only 6-8 seconds under the line where a run bills 3.
Around the clock comes to about 1,530 minutes a month at 2 and 2,280 at 3,
against the Free plan's 2,000, so the loop stays on waking hours until a week
of scheduled runs shows how often they cross 120 seconds. The first real runs
should push at most 2 listings, both Mac Studio M3 Ultra 96GB on eBay, and
email about 23 deals at STRONG or better.

**First scheduled runs, 2026-09-17.** GitHub took almost six hours after #2
merged to pick up the new schedule, then fired both hardware runs back to back
at 07:57 UTC:

| Run    | Assessed | Problems | Job time | Sent                  |
|--------|----------|----------|----------|-----------------------|
| fast   | 607      | 0        | 140 s    | 2 ntfy pushes         |
| digest | 605      | 0        | 116 s    | 1 email with 19 deals |

Both committed "Update deal evidence and delivery receipts". The push loop's
first real run billed 3 minutes. Before this, GitHub created only about 1 in 10
of this repo's 15-minute scheduled runs, with gaps of up to 5.5 hours, and it
ran the old Steam repo's daily job 2 to 3.5 hours late. Expect the push loop to
run a few times a day rather than hourly, with pushes arriving hours after a
listing appears. Revisit that once there is a day of real runs.

After section 1, turn on the daily digest:

```bash
gh variable set ENABLE_HARDWARE --body true -R jcscocca/deal-alerter
```

Once `NTFY_TOPIC` or `DISCORD_WEBHOOK` is set, turn on the hourly push loop:

```bash
gh variable set ENABLE_HARDWARE_FAST --body true -R jcscocca/deal-alerter
```

Check it with a dry run:

```bash
gh workflow run check.yml -R jcscocca/deal-alerter -f domain=hardware -f mode=digest -f dry_run=true
```

Without eBay this assessed 6 listings with 0 problems in about 110 seconds;
with eBay it should find more. Note how long the run takes. The push loop is
held to 14:00-06:00 UTC to fit the Free plan's Actions minutes (the comment in
`check.yml` has the arithmetic), so if a run with eBay stays under two
minutes, hourly around the clock may fit. After the first real scheduled run,
look for a bot commit, "Update deal evidence and delivery receipts", touching
`state/hardware/US/prices.jsonl`.

## 5. Retire the old repos

Once Steam and hardware have each completed a real scheduled run, and
section 1 is done:

1. In each old repo, set `"status"` in `.project-steward.json` to
   `"archived"`, replace `SUPERSEDED.md` with a short note that it is retired
   in favour of `jcscocca/deal-alerter`, then commit and push.
2. Archive both:

   ```bash
   gh repo archive jcscoccaprivate/steam-deal-alerter --yes
   gh repo archive jcscoccaprivate/ai-deal-alerter --yes
   ```

3. Delete this file.

## Later, not blocking

- Reddit's anonymous throttling is most of a hardware run. Fetching one
  combined feed, `r/buildapcsales+homelabsales+hardwareswap/new.rss`, instead
  of three would cut it, possibly enough for round-the-clock hourly checks.
- `tests.yml` also runs on docs-only pushes. Add `'**.md'` to its
  `paths-ignore` if minutes get tight.
