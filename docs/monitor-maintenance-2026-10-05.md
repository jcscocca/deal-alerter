# Monitor maintenance follow-up — October 5, 2026

The user approved continuing the live upgrade and scheduling a physical reboot
and network recovery test afterwards. They also confirmed that Reddit does not
issue usable API credentials for this project; the repository already records
that limitation.

## Accessible community evidence

The public Slickdeals Computers category at
`https://slickdeals.net/computer-deals/?sort=newest` is accessible with the
monitor's declared User-Agent and allowed by its fetched robots policy. The
observed first page supplied 40 recent deal cards with explicit Unix posting
timestamps and expired flags. The new adapter reads these fields, retains
stable thread IDs, excludes expired/unknown/stale/unsafe cards and leaves the
bounded coverage warning visible. The saved fixture contains one small public
card excerpt; active stock and complete-PC offers remain unconfirmed notices.

Slickdeals search RSS and all anonymous Reddit paths remain policy blocked.
The category restores useful partial coverage; it does not claim exhaustive
search results. HP's old GT22-3090 and current GT23-0990m fixed-product pages
both reproduced read timeouts. HP robots policy permits the product path, but
that alone does not establish accessible product/configuration evidence.
No access policy, challenge or credential restriction was bypassed.

## Recovery acceptance

`Test-MonitorRecovery.ps1` prepares a one-time protected SYSTEM boot verifier,
with receipt and active-adapter baselines. After the approved reboot it checks
startup/PID, physical disconnection, ongoing heartbeat, source retry/recovery,
and retention of prior delivery receipts. A separate one-time SYSTEM restore
task protects networking if the verifier is interrupted. It records partial
rather than complete no-login acceptance if the user logs in before startup.
Actual reboot/network results are written to the installed runtime's
`acceptance/recovery-result.json`; preparation and fixture tests cannot
establish that those physical checks have happened.

The new category URL also gives its job a new identity, so the old disallowed
RSS path's six-hour delay cannot postpone the new route. Shared server/host
cooldowns remain intact across the change.

Local validation passed 1,000 tests and 58 subtests. Both installer regressions
passed. Windows Task Scheduler validated both acceptance task definitions
without registering them or changing networking. CI now repeats that task
validation on Windows.

The live upgrade and physical acceptance remain pending until their elevated
execution and recorded results. Issue #36 retains the external HP/Reddit
limitations; #37 and #38 track physical acceptance and runtime maintenance.
