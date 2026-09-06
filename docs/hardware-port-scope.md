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

## The remaining work is narrow and already marked

The inherited suite runs **446 passed** here against **475 passed** in
`ai-deal-alerter`. That gap is not scattered — it sits on the two modules above:

- **16 tests** construct the pre-migration `Config` (`smtp_host` and siblings now
  live in `dealcore.config` / `dealcore.notify`). Finishing the config port fixes
  these.
- **4 tests** in `tests/pending_entrypoint/` import the retired `check_deals`
  entry point. They become collectable once the hardware domain runs through
  `dealcore.run`. Kept verbatim rather than deleted; they are coverage that must
  survive.
- **21 errors** are Windows temp-directory permission failures that do not
  reproduce in the control repo. Environmental, not a porting defect.

One pre-existing failure in the source repository —
`test_variant_listings.py::TestAlertKeysCollapse::test_an_old_file_is_migrated_rather_than_orphaned`
— predates the consolidation. Do not read it as a regression.

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

1. The inherited suite here reaches parity with the control count.
2. `tests/pending_entrypoint/` is collectable again.
3. Both alerters have run in parallel long enough to compare real alerts.
