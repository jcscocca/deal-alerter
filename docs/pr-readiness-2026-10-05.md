# PR review — October 5, 2026

The three parsing fixes remain relevant. The external GitHub dispatch proposal
is superseded by the installed ThinkPad monitor. No merge, live upgrade, task
restart, schedule change or notification was performed during this review.

| PR | Decision | Remaining work |
| --- | --- | --- |
| [#22](https://github.com/jcscocca/deal-alerter/pull/22) | Merge server detection fix | Updated against main; added protection for cards that call VRAM RAM, with regressions for both cards and complete servers. |
| [#32](https://github.com/jcscocca/deal-alerter/pull/32) | Merge PC detection fix | Install in the live monitor after merge. |
| [#33](https://github.com/jcscocca/deal-alerter/pull/33) | Merge Slickdeals condition fix | Install in the live monitor after merge. |
| [#21](https://github.com/jcscocca/deal-alerter/pull/21) | Close as superseded | Conflict resolved and pushed, retaining self-hosted runner isolation and the hardware ownership guard. External dispatch remains an inactive proposal. |

## Historical evidence repair

`scripts/repair_hardware_history.py` repairs exact source, listing ID, part and
title combinations from these audits. It removes every price variant of the
four complete-machine listings, moves Staples Slickdeals thread 20088846 to
`new`, and moves Woot factory-reconditioned thread 19883949 to `refurb`.
All other metadata and successful-delivery receipts are preserved.

The Git history repair removes **five** observations and moves **two**. The
live dry run at approximately 7:45 PM PDT found **six** observations to remove
and the same two moves: the old runtime added a second price for the Intel
Ultra 9 computer, $6,082.05, after the committed $6,093.45 observation.
Counts can increase before the fixed parser is installed.

Read-only inspection:

```powershell
python scripts/repair_hardware_history.py state/hardware/US/prices.jsonl
python scripts/repair_hardware_history.py C:\ProgramData\DealAlerter\state\hardware\US\prices.jsonl
```

For live application, first merge and install the reviewed parsing fixes using
the [upgrade procedure](thinkpad-monitor.md#rollback-and-upgrades). Keep both
hardware and watchdog tasks stopped during the upgrade and repair. Retain the
live runtime's current state and receipts; do not copy the Git history over it.
Then use the updated checkout/runtime's Python to apply:

```powershell
python scripts/repair_hardware_history.py C:\ProgramData\DealAlerter\state\hardware\US\prices.jsonl --apply --backup C:\ProgramData\DealAlerter\prices.before-pr-audit.jsonl
```

The apply operation takes the monitor's hardware writer lock, refuses an
existing backup, backs up the exact original bytes and atomically replaces only
`prices.jsonl`. Invalid JSON aborts before changing history. An idempotent rerun
does not rewrite files. Restart both tasks after the upgrade and repair, and
verify fresh health and preserved receipts. Live maintenance needs approval
because it replaces the application used to send alerts and interrupts polling.

## Operational loose ends

- GitHub variables confirm `HARDWARE_WRITER=thinkpad`, both hardware switches
  disabled, and Steam enabled. Scheduled skipped hardware runs are expected.
- The local monitor has a fresh heartbeat and successful eBay, Apple and
  Skytech/Newegg checks, but its separate installed snapshot lacks these PR fixes.
- HP has no successful live check. Reddit and Slickdeals are policy-blocked.
  Twelve discovered Newegg pages also have no confirmed seller/configuration/
  landed total; successful Skytech checks do not establish ABS coverage.
- A physical reboot and network-disconnection recovery test remain unverified
  in the activation record. Local monitoring also cannot report a powered-off
  ThinkPad from outside; an external availability check would be separate work.
- Git hardware history is a cutover-era recovery copy. Live observations now
  belong to `C:\ProgramData\DealAlerter\state`; merging a Git-only cleanup does
  not repair the active monitor's history.

## Verification

The repair regression suite covers price variants, condition moves, unchanged
metadata, dry-run immutability, idempotence, reused listing IDs, active-writer
exclusion, corrupt JSON, backup collisions, receipts and LF/CRLF preservation.
The server fix's full Python 3.11 suite passed 934 tests and 58 subtests; the
resolved scheduler proposal passed the unchanged 928-test suite and 58 subtests.
The final combined test result is recorded in the cleanup PR description.
