# Review follow-up — October 5, 2026

PRs #22, #32, #33, #34 and #21 were merged at the user's request, in that order.
The complete combination passed 957 tests and 58 subtests before merging.
External dispatch support is merged but inactive; ThinkPad remains the hardware
writer and Steam remains on GitHub. No external scheduler was enabled.

## History corrections

The older title-verified backlog is now included in the exact-match maintenance
script. Its Git recovery-history migration removes five mobile/whole-system
observations and corrects eleven SKU assignments. Prices, conditions, quantities,
sold flags and first/last-seen times are preserved on SKU corrections.

The user chose to archive the 564 legacy observations without titles and exclude
them from comparisons. `prices-unaudited.jsonl` retains all their original
evidence. Archive persistence precedes active-history replacement, so an
interruption cannot lose a quarantined row. Exact-row dedup makes retry safe.

The live preview includes the previously merged audit corrections as well:
eleven removals, thirteen condition/SKU corrections and 564 archived rows at
the time inspected. Current live data is repaired under its own writer lock;
the Git recovery file is never copied over it.

## Newegg coverage

A real selected ABS page, 83-360-990C, exposes blank seller fields in ItemDetail
but an explicit primary `Sold by Newegg` label. The adapter now accepts that
combination. It rejects conflicting marketplace IDs, multiple primary seller
labels, and shipping-only or non-Newegg claims. The saved public fixture was
observed October 5 at 8:02 PM PDT: refurbished, out of stock, $4,999.99 with
free shipping. This records parser evidence, not current availability.

## Live upgrade and recovery

`Update-Monitor.ps1` packages the protected application upgrade, state backup,
repair and task restart without rerunning initial cutover. Its read-only
validation checks merged code, hashes, existing dependencies, owner manifest
and GitHub writer gates. Applying needs Windows administrator elevation; the
Codex session runs as a standard user and has read-only runtime access.

Network-recovery regression coverage now simulates a request timeout, verifies
the host cooldown suppresses premature retries, then confirms recovery after
the cooldown without discarding the cached access policy. Existing regressions
cover startup state, persistent backoff, watchdog restart and receipt retries.
A physical reboot/network-disconnection test is still a separate disruptive
acceptance check; simulated recovery does not establish physical boot behavior.

HP still has no successful live result. Reddit and Slickdeals feed paths remain
policy-blocked; Reddit's implemented API route needs locally provisioned API
credentials. These access gaps are reported by the watchdog rather than hidden
or bypassed. An external check for a completely unavailable ThinkPad is not
configured; no service/account or recurring monitor was created for it.
