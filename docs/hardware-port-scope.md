# Hardware domain: what gets ported, what stays vendored

A decision record. The consolidation brought the Steam domain across as a full
port and the hardware domain as a vendored copy under
`alerters/hardware/native/`. That asymmetry looked like unfinished work. It is
mostly not, and this records which part is which so nobody ports the wrong things.

## The rule

**Vendoring is correct where a module has no counterpart in the core. Porting is
required only where a module duplicates something the core already owns.**

The whole point of the consolidation was to stop maintaining two copies of the
same logic. It was never to force domain knowledge through a generic layer.

## Where each native module lands

| Module | Lines | Core counterpart | Decision |
|---|---|---|---|
| `match.py` | 786 | none | **Stays vendored.** Regex and judgment separating a real 3090 from a cardboard box from e-waste. Steam needs none of it. Pushing this into shared code or configuration would make it unreadable and undebuggable. |
| `catalog.py` | 472 | none | **Stays vendored.** Known parts and reference prices. |
| `rig.py` | 243 | none | **Stays vendored.** The capability-gain axis. Steam has one judgment axis; hardware has three. The core is deliberately indifferent to axis count. |
| `sources/` | ~930 | none | **Stays vendored.** eBay, Reddit, Slickdeals, Apple. |
| `history.py` | 383 | none | **Stays vendored.** Hardware accumulates its own price history because no ITAD exists for GPUs. Steam delegates history to an API. The core expresses both as capabilities; the accumulation logic itself is domain work. |
| `verdict.py` | 639 | `dealcore/verdict.py` (69) | **Port.** This is real duplication — 41 references to band, ordering, and formatting concepts the core now owns. |
| `config.py` | 366 | `dealcore/config.py` | **Port — already in progress.** Notification config moved to `dealcore.config` / `dealcore.notify`; the rest has not followed. |

Five of seven stay. The adapter already routes correctly: `alerters/hardware/plugin.py`
imports `RunOptions`, `atomic_write`, `AccumulatedHistory`, `Assessment`, `Card`,
`FetchResult`, `Listing`, `Report`, `Improvement`, `band`, and `money` from the core.

## Test coverage: resolved

The inherited suite now runs **483 passed, 0 failed** here, against **475 passed**
in `ai-deal-alerter`. The gap that existed on first import was entirely on the
migration seam, not in the ported logic:

- `pytest.ini` had not been carried across. The source repository pins
  `--basetemp=.pytest_tmp` with a comment explaining that the Windows system
  temp root is not always writable and that the failure surfaces as an opaque
  `PermissionError` from inside pytest. Dropping it cost 21 spurious errors.
  **Restored.**
- `AlertState` moved to `dealcore.state`, taking the domain's normaliser and
  per-channel delivery records. The key-collapse tests were rewritten against
  `is_new()` / `record()`; they now exercise the plugin seam rather than a
  hardcoded eBay rule.
- `dedupe` moved to `dealcore.run` and takes the domain's key function.
- Mode-dependent credential validation moved from `Config.load(need_email=,
  need_push=)` to `dealcore.notify.channels(email=, push=)`. Same guarantee,
  now shared by both domains.

**Four tests remain quarantined** in `tests/pending_entrypoint/`. `show_stats`
is now a `HardwarePlugin` method rather than a free function; `evaluate` and
`price_stats` have no successor, their orchestration having split across
`dealcore.run` and the plugin's `prepare`/`judge`. `tests/conftest.py` records
what each needs. They are kept verbatim, not deleted.

A time-bomb in the source repository has also been fixed there: the alert
migration test pinned `pushed_at` to an absolute date, and once that drifted
past `remind_after_days` the reminder window had genuinely elapsed, so the test
reported a migration failure that never happened. It had been red in CI since
2026-08-18 for that reason alone.

## Do not lose these while porting `verdict.py`

Hardware bands are `PASS / FAIR / GOOD / STRONG / EXCEPTIONAL / GRAIL`; Steam
bands are `WAIT / DECENT / BEST_THIS_YEAR / NEAR_LOW / MATCHES_LOW / ALL_TIME_LOW`.
The core requires an ordered enum and nothing else — `dealcore/verdict.py` opens
with *"No knowledge of any band's name."* Do not collapse the two vocabularies.

`dealcore.verdict.qualifies` raises `TypeError` when an assessment and a threshold
use different band enums, because `IntEnum` otherwise compares across unrelated
enums silently and a Steam band would satisfy a hardware threshold. Keep that.

Hardware's re-alert improvement rule is a 4% drop; Steam's is a cent epsilon.
`Improvement` in the core expresses both. They are structurally different rules,
not the same rule with different constants.

## Retire `ai-deal-alerter` when

1. ~~The inherited suite reaches parity with the control count.~~ **Done** — 483 passed against 475.
2. `tests/pending_entrypoint/` is collectable again.
3. Both alerters have run in parallel long enough to compare real alerts.
