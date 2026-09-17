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
| `verdict.py` | 639 | `dealcore/verdict.py` (69) | **Ported.** Takes `ago` and `money` from the core; `DOLLAR` feeds the core's `Improvement`. What remains is the three-axis hardware judgment — `_decide`, `_decide_from_history`, `_verdict_from_anchor`, `_decide_from_reference`, `_value_sentence` — which has no core counterpart and stays. |
| `config.py` | 366 | `dealcore/config.py` | **Ported.** Notification settings live in `dealcore.config` / `dealcore.notify`; `overlay` and `read_config` come from the core. `Thresholds`, `Hunt`, `load_watchlist` and the hardware `Config` fields are domain-owned and stay. |

An earlier revision of this document listed the last two as outstanding work
based on a crude symbol count. That was wrong: most of the 639 lines in
`verdict.py` are the hardware judgment itself, not duplicated mechanics.
**No core symbol is re-implemented in `native/` — verified by sweep.**

The adapter routes correctly: `alerters/hardware/plugin.py` imports `RunOptions`,
`atomic_write`, `AccumulatedHistory`, `Assessment`, `Card`, `FetchResult`,
`Listing`, `Report`, `Improvement`, `band`, and `money` from the core.

`history.export_jsonl` now writes through the core's `atomic_write`. It rewrites
the committed price log whole on every run, so a crash or cancelled CI job
partway through a plain `open("w")` truncated it — and there is no second copy
of a log that took months to accumulate. Covered by two tests.

## Test coverage: resolved

The inherited suite now runs **485 passed, 0 failed** here, against **475 passed**
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

**The four quarantined tests are restored.** `test_dry_run`, `test_stats`,
`test_threshold_bands` and `test_trust` sat in `tests/pending_entrypoint/`
because they imported the retired `check_deals` entry point. They now drive its
replacement: `tests/hardware_pipeline.py` runs `dealcore.run` over the shipped
config with a stub source and reads the log back from the persisted JSONL.
Their assertions did not change. Restoring `test_stats` caught a regression the
port had introduced -- `--stats` printed `median=1100.0` and had lost its low
and p25 columns -- and the original table was restored rather than the test
loosened. The suite is at 681 passed.

A time-bomb in the source repository has also been fixed there: the alert
migration test pinned `pushed_at` to an absolute date, and once that drifted
past `remind_after_days` the reminder window had genuinely elapsed, so the test
reported a migration failure that never happened. It had been red in CI since
2026-08-18 for that reason alone.

## Do not lose these if you touch `verdict.py`

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

1. ~~The inherited suite reaches parity with the control count.~~ **Done** — 485 passed against 476.
2. ~~`tests/pending_entrypoint/` is collectable again.~~ **Done** — restored, see above.
3. ~~Both alerters have run in parallel long enough to compare real alerts.~~
   **Dropped.** The old hardware alerter stopped collecting on 2026-08-17, so
   there was nothing left to run in parallel with, and every day spent waiting
   was a day missing from the price log. Cut over directly instead.
