# Next steps: finish the cutover

Written 2026-09-16 on the Windows machine, for picking up on the Mac. Work
through the sections in order, and delete this file when section 5 is done.

Credentials are yours to set. A Claude session should hand you the secret
commands below rather than run them itself.

## Where things stand

- **Merged** ([#1](https://github.com/jcscocca/deal-alerter/pull/1)): tests run
  in `tests.yml` and pass at 681 on Python 3.11 and 3.14, scheduled runs in
  `check.yml` only check deals, the four quarantined hardware tests are
  restored, and the README describes the product.
- **Nothing is scheduled yet.** Every `ENABLE_*` repository variable is unset,
  and `STEAM_ID` is the only secret.
- **The only live alerting** is the old Steam alerter,
  `jcscoccaprivate/steam-deal-alerter`, daily at 18:15 UTC.
- **Hardware has been dark since 2026-08-17.** The committed price log holds
  1,417 observations from Aug 8-17, identical in both repos. It never reached
  the 14-day span percentiles need, so every hardware verdict so far has been
  reference-based.
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

**Done 2026-09-16 on the Mac, except stopping the agents.** Both agents were
still loaded but had failed every run since 2026-08-19 because
`~/Repos/ai-deal-alerter/.venv` no longer exists (digest exits 127 daily at
09:00, fast exits 78 every 15 min). The Mac's log had 203 rows newer than the
committed one and none missing, and no changes outside `state/`; both files are
copied into `state/hardware/US/`, stats and the 681 tests pass. The only thing
left in this section is the `launchctl bootout` block below.

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

The Mac's old `.env` has every key `check.yml` reads, including Reddit API
credentials the Windows one lacked (these should cut the Reddit throttling
noted under "Later"). Its `SMTP_HOST`, `SMTP_PORT` and `NTFY_SERVER` match the
workflow defaults, so no repository variables are needed. This sends only the settings that have a value, and prints none:

```bash
grep -E '^(SMTP_USER|SMTP_PASSWORD|MAIL_FROM|MAIL_TO|NTFY_TOPIC|NTFY_TOKEN|DISCORD_WEBHOOK|EBAY_CLIENT_ID|EBAY_CLIENT_SECRET|REDDIT_CLIENT_ID|REDDIT_CLIENT_SECRET)=.+' ~/Repos/ai-deal-alerter/.env | gh secret set -f - -R jcscocca/deal-alerter
```

The IsThereAnyDeal key is shown at isthereanydeal.com/apps/my:

```bash
gh secret set ITAD_API_KEY -R jcscocca/deal-alerter
```

```bash
gh secret list -R jcscocca/deal-alerter
```

One `MAIL_TO` now serves both domains; comma-separate several addresses. If
the mail server is not Gmail on port 587, also set the repository variables
`SMTP_HOST` and `SMTP_PORT`.

## 3. Steam cutover -- in this order

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
