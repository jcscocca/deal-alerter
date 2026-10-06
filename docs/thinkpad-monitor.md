# ThinkPad RTX 5090 monitor

The local monitor preserves `config/watchlist.toml`'s $5,000 RTX 5090 target
and the `RTX 5090 gaming PC` query. It uses `dealcore.run`, the existing ntfy
transport, per-channel successful-delivery receipts, and the existing 5%
same-condition loose-GPU undercut promotion. Other hardware hunts continue
through the existing eBay/Apple sources; Reddit still includes other watched
hardware when accessible. Steam remains on GitHub Actions.

## Commands and files

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alerters.hardware.monitor --once --dry-run --runtime .local\live-dry-run
.\.venv\Scripts\python.exe -m alerters.hardware.monitor --status --runtime .local\live-dry-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Prepare-Monitor.ps1
```

Dry runs make HTML previews and diagnostic files under the runtime directory;
they send nothing and do not write observations, offer transitions or receipts.
One-shot dry runs check the configured seed/discovery/feed jobs once and list
new product URLs for subsequent polling. They do not recursively crawl every
new discovery. Exit 1 means partial coverage/delivery failure; exit 2 means a
configuration/state failure. `health.json` lists every job and its last success,
next attempt and sanitized failure. Rotating logs retain five 2 MB files.

`config/monitor.toml` requests a 120-second interval after each successful
retailer check, 300 seconds for feeds, 600 seconds for retailer discovery,
900 seconds for eBay and one hour for Apple refurb. Fetch jobs run concurrently;
only the main process judges, sends and writes state. A slow retailer/feed
does not hold up a different host. Each public host has a two-second minimum
request gap (or its longer robots crawl delay). Product discovery is bounded
to 24 URLs per retailer and reports a coverage warning when full. Search
results are partial discovery, never proof of delisting. The seed URL remains
watched after it drops out of search results.

Retailers use conditional requests where supported. HTTP 429/503 Retry-After
(seconds or HTTP date), exponential backoff and host cooldown survive restarts.
403s/challenges are backed off, not bypassed. Robots policies are refreshed
every six hours; unverifiable policies fail closed. No cart, login, payment or
private retailer API calls are made. Cadence is a target, not a delivery SLA.

Slickdeals discovery uses the public Computers category sorted newest first.
Its explicit posting timestamps and expired flags are checked before assessing
rows. Only the first page is read; it cannot establish exhaustive search coverage
or delisting. The coverage limit remains visible in health and watchdog reports.
Slickdeals search RSS and anonymous Reddit RSS remain blocked by their robots
policies. New Reddit API credentials are unavailable to this user, as recorded
in the repository's Reddit source notes; that gap remains reported.

## Offer evidence and notifications

Newegg confirmation uses its public `window.__initialState__.ItemDetail` and
`PropertyCollection.SelectedProperty`. Product identity includes the selected
seller item, configuration and condition. A 5080 selected under a family page
mentioning a 5090 is rejected. Only ABS/Skytech desktop configurations qualify.
The current trusted seller mapping accepts the Skytech store ID A1HJ and
Newegg's own seller identity; third-party sellers remain unconfirmed.

HP confirmation requires a primary fixed-SKU Product/Offer matching the page's
heading, exact desktop RTX 5090 inclusion, a real USD price and known stock.
Zero placeholders, aggregate/from prices and configurable base-SKU prices fail
closed. **Dynamic HP custom builds are not yet confirmed by this adapter**;
they need a public fixed selected-configuration representation before they can
produce confirmed offers. Broad OMEN marketing text is insufficient.

Announcements and community offers are separate unverified notices. A post
without a price can still notify. Explicit ISO dates or dates/relative days
with explicit PT/PST/PDT/ET/EST/EDT/UTC are converted to Pacific time, including
DST. Ambiguous DST folds/gaps and unspecified time zones stay unknown. A due
announcement schedules the purchase URL for rechecking, while preserving rate
backoff; unsupported purchase URLs trigger a feed recheck. A start time passing
never makes an announcement a confirmed offer. Edits to a post retain its
identity. Recurring known product checks continue after the first start recheck.

Confirmed live offers at or under $5,000 use these ntfy priorities:

| Complete cost before tax | Priority |
| --- | --- |
| $4,500–$5,000 | 3 (normal) |
| $4,000–under $4,500 | 4 (high) |
| Under $4,000 | 5 (highest) |

The complete cost is PC price minus eligible coupon discounts plus shipping and
all required accessories. Unknown shipping/accessory costs prevent a confirmed
total. Cashback is never deducted. Newegg coupon deductions require explicit
product-scoped amounts and unrestricted terms. Optional reviewed coupon rules
can specify exact SKU, known eligibility, costs, instructions and expiry; the
code must remain published on the product page. Student, membership and credit
card eligibility is never assumed. HP accessory coupon badges do not discount
the PC. Unverified coupon amounts are displayed but excluded from the total.

Upcoming-sale, live-deal and restock cards carry the actual specs, condition,
seller, stock, component costs, coupon instructions, start/end time if known,
and purchase link. Unverified notices stay at normal priority. Above-target
systems can still qualify through the existing 5% same-condition undercut rule,
using fresh eligible loose-GPU evidence (at most 20 minutes old).

`prebuilt-prices.jsonl` contains complete-PC observations, keyed by retailer SKU,
seller, exact configuration and condition. New, refurbished and open-box are
separate. No prebuilt observation enters `prices.jsonl` or its GPU percentiles.
`prebuilt-offers.json` records stock/sale transitions. These facts are persisted
before sending; `alerts.json` records a revision only after successful delivery.
An unchanged offer does not get a weekly repeat. A cumulative price change of
at least max($25, 1%), crossing a priority/target boundary, a coupon/sale change
or a confirmed out-of-stock to in-stock transition creates a new revision.
There is still a small send-before-receipt crash window, as in the original core.

## Prepared Windows startup

`Prepare-Monitor.ps1` creates a hashed application snapshot, secret-name template
and two task XML files in `.local/windows`. It does **not** register tasks,
change GitHub variables, send a notification or move live state.

The proposed runtime is `C:\ProgramData\DealAlerter`:

- `app/`: reviewed application snapshot; independent of the editable checkout.
- `venv/`: Python runtime using `pythonw.exe`, with no visible console.
- `secrets.env`: local ntfy/eBay/SMTP credentials; SYSTEM/Administrators ACL only.
- `state/hardware/US/`: sole live hardware history and successful-delivery receipts.
- `owner.json`: approved ownership manifest, binding code and state paths.
- `health.json`, `watchdog.json`, `schedule.json`, rotating `monitor.log`.

`DealAlerter-Hardware` runs as SYSTEM 45 seconds after boot, without requiring a
login. Task Scheduler restarts failures every minute. `DealAlerter-Watchdog`
runs at boot and every minute, detects a heartbeat older than 90 seconds,
restarts a stopped/hung monitor after 120 seconds, and reports stale source
checks (max(10 minutes, three intervals)). It records transport receipts for
health warnings as well. Restart is independent of ntfy connectivity. Both
tasks allow battery operation and request wake timers; neither changes the
machine's power plan. The process uses an OS lock, released on crashes, and the
legacy hardware CLI refuses real writes when the machine has a local owner.

A powered-off, sleeping or disconnected laptop cannot send an immediate remote
warning by itself. Local heartbeat/watchdog logs detect stale monitoring on
recovery. Detecting a completely dead ThinkPad from outside it would need a
separately approved external dead-man check. No paid infrastructure is involved.

## Cutover checklist — requires approval

1. Review the verified dry-run report and access gaps. Restore accessible HP/feed
   coverage or explicitly accept degraded coverage. Obtain local credentials
   through their normal provisioning path. GitHub only reveals secret names,
   not existing secret values. Do not paste values into chat or commit them.
2. Review/merge this code, including the `HARDWARE_WRITER` workflow guard.
   Fetch current `origin/main`, preserve any local edits, retest and prepare a
   fresh snapshot. The installer refuses an unreviewed upstream code change or
   a main branch without the manual-dispatch ownership guard.
3. With approval, create `C:\ProgramData\DealAlerter\secrets.env` in an elevated
   local session. ntfy, eBay and SMTP are required to retain existing hardware
   functionality. Reddit credentials are optional but anonymous access may be
   blocked. Restrict the file ACL before adding values.
   Alternatively, run `scripts/windows/Prepare-Credentials.ps1` locally, then
   manually dispatch `provision-thinkpad.yml` on main with its one-time request ID.
   This owner-only workflow uses the existing `THINKPAD-wsl-deal-alerter` runner
   to write GitHub secrets into a private WSL directory (0700, file 0600). Run
   `Import-Credentials.ps1 -PythonExe <absolute-python-path>` to copy them through
   a captured pipe into the ACL-protected `.local/credentials` directory and delete the
   WSL copy. Keeping staging outside AppData avoids different filesystem views
   between packaged applications, runner services and elevated sessions.
   Neither step prints values or uploads an artifact. Pass the Windows file to the elevated
   installer as `-SecretsFile`; remove the staging copy after successful cutover.
   The installer grants the owner read access to health/state, while keeping
   the installed secrets file restricted to SYSTEM and administrators.
4. With approval, run `Enable-Monitor.ps1 -ApproveCutover` with the prepared
   directory and an absolute Python 3.11+ executable. It records the old switches,
   sets `HARDWARE_WRITER=thinkpad`, disables `ENABLE_HARDWARE_FAST` **and**
   `ENABLE_HARDWARE`, and refuses to continue while any check-deals workflow is
   queued/running. It does not cancel Steam or change `ENABLE_STEAM`.
5. Let existing runs drain, rerunning the approved installer if needed. It fetches
   again and snapshots **only current `origin/main` hardware state** after draining.
   The old snapshot is retained as `hardware-cutover.zip`. It installs the reviewed
   code, private venv and ACLs, writes the owner manifest, registers and starts the
   two dedicated tasks. No service runs before the remote hardware gates close.
6. Inspect task results and health under SYSTEM, then verify fresh retailer
   observations, restart after reboot, network recovery and receipt persistence.
   These real startup/reboot checks remain pending until enablement is approved.
   A test push is a separate explicit approval. Ordinary live alerts and monitor
   health warnings begin when the approved service is enabled.
7. Retain encrypted/private backups of the runtime state. The ThinkPad does not
   git-push its state, so Steam state commits cannot conflict with local hardware.
   Keep all scheduled/manual GitHub hardware writes gated while it owns state.

The Steam cron remains `22 18 * * *`, its existing UTC schedule. Its switch is
untouched. Hardware's old crons remain in source but are gated off at cutover.
The workflow stages only the resolved domain's state.

## Rollback and upgrades

For rollback, stop and disable **both** dedicated Windows tasks, verify the OS
writer lock is released, and back up the entire runtime first. Export the local
`state/hardware` files into a clean checkout based on freshly fetched main;
review and commit **only hardware state** so its delivery receipts survive.
If main changed hardware state after cutover, reconcile it explicitly. Never
overwrite Steam state or force-push. Push the hardware state commit successfully
before restoring the hardware switches saved in `prior-switches.json` and
clearing/restoring `HARDWARE_WRITER`. Remove the local owner manifest only after
the local tasks are stopped. Keep the runtime backup for recovery. This rollback
requires approval because it changes live schedules.

For upgrades, stop the two tasks, retain the live state/receipts, replace only
the reviewed application snapshot and dependencies, then restart and inspect
health. Do not rerun the initial cutover installer over an existing owner; it
intentionally refuses to seed stale GitHub hardware state over local history.

For a release with unchanged dependencies, use the reviewed maintenance helper:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Prepare-Monitor.ps1 -OutputDirectory .local/upgrade
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Update-Monitor.ps1 -PreparedDirectory .local/upgrade -ValidateOnly
# Run the apply command in an elevated Windows session after validation:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Update-Monitor.ps1 -PreparedDirectory .local/upgrade -ApproveUpgrade
```

The helper verifies a clean merged package, the installed owner and closed
GitHub hardware gates before disabling the watchdog and hardware tasks. It
backs up application/state/owner/task definitions without copying secrets,
verifies the writer lock is released, installs hashed files, applies the
audited history repair and approved titleless-row quarantine, then restarts
the tasks and requires a fresh heartbeat. It keeps live receipts and records
`installed_commit` in the owner manifest. On failure it restores the old
application and enabled tasks while retaining all history and delivery receipts.
It refuses dependency changes rather than modifying the active environment.

The lock probe returns a quiet retry status for ordinary contention, including
under Windows PowerShell 5.1. It separately rejects unexpected I/O/import errors.
Maintenance waits for the prior PID and scheduled task instances to exit as
well as for the writer lock to become available before copying application
files. Success and rollback both start hardware first and require its new
heartbeat before starting the watchdog. Failed upgrades record a separate
`recovery_status` so a failed restart cannot masquerade as a completed rollback.

## Approved physical recovery acceptance

The recovery preflight accepts the Task Scheduler default of an enabled boot
trigger when exported XML omits `Enabled`. An explicit disabled trigger or a
missing boot trigger still fails. The Windows regression compares this check
with Task Scheduler's XML parser, including its normalized exports.

After applying the merged release, run the installed helper in an elevated
session. It validates existing SYSTEM boot tasks, battery/wake settings, ownership
and a fresh heartbeat before scheduling a disruptive check:

```powershell
& C:\ProgramData\DealAlerter\app\scripts\windows\Test-MonitorRecovery.ps1 -ValidateOnly
# Only after the user has saved work and approved reboot/network interruption:
& C:\ProgramData\DealAlerter\app\scripts\windows\Test-MonitorRecovery.ps1 -ApproveReboot
```

Windows schedules a reboot in two minutes; `shutdown /a` cancels that countdown.
Save all open work before approval. Leave the computer signed out for the first
two minutes after restart so the check can establish startup before interactive
logon. A one-time hidden SYSTEM task starts 90 seconds after boot, verifies the
new monitor process, waits for a healthy retailer job to become due, and disables
the original active physical adapters for 60 seconds. It re-enables them in a
`finally` block; an independent one-time SYSTEM task also requests restoration
after 90 seconds if the verifier is interrupted.

The verifier waits up to ten minutes for that same retailer to succeed again,
requires the monitor heartbeat and PID to survive the outage, and checks that
prior delivery receipts have not disappeared or moved backwards. Existing
regressions establish duplicate suppression; receipt retention alone cannot
prove what a remote notification recipient received. No test notification is
sent. Power-plan settings are inspected, not changed.

`C:\ProgramData\DealAlerter\acceptance\recovery-result.json` records complete,
partial or failed evidence. A logon before monitor startup leaves no-login
acceptance explicitly partial. The acceptance tasks remove themselves when
finished; a restore task is retained if the adapters are not up. This acceptance
does not claim to restore blocked HP/Reddit access or provide external dead-host
coverage.

If installation fails after closing GitHub gates, hardware monitoring stays
paused. Diagnose from the installer output and saved prior switches; do not
automatically start both writers to recover. Steam continues independently.
