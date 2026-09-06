# Hardware migration map

## Every Part 3 module

| Original | Destination | Treatment and resistance |
|---|---|---|
| `sda/itad.py` | `alerters/steam/sources.py`, `alerters/steam/history.py` | New concrete API transport implementing the supplied shapes. Current-price intake and delegated history share a client, not a responsibility. Native `HistoryStats` and episode reasoning stay in `judgment.py`. |
| `sda/steam.py` | `alerters/steam/sources.py` | Concrete wishlist/vanity intake. A failed or ambiguous wishlist response is not an authoritative empty wishlist. |
| `ada/history.py` | `alerters/hardware/native/history.py` unchanged; orchestration in `alerters/hardware/plugin.py` | Resists extraction into core. Condition buckets, asking versus sold distributions, quantiles, minimum observation count, minimum span and reference confidence are hardware semantics. SQLite remains a disposable local cache; JSONL remains durable. |
| `ada/match.py` | `alerters/hardware/native/match.py` unchanged | All actual regexes, alias specificity, have/want parsing, mobile/accessory exclusions, quantity, capacity checks and ambiguity judgments survive. No rule language and no replacement matcher inferred from signatures. |
| `ada/catalog.py` | `alerters/hardware/native/catalog.py` unchanged | Parts, classes, bandwidth, reference prices and sold/estimate provenance remain domain evidence. No fabricated replacement catalog. |
| `ada/rig.py` | `alerters/hardware/native/rig.py` unchanged | Machine topology, power, capacity and model fit remain ordinary Python. The adapter prevents a target override from undoing the no-upgrade cap. |
| `ada/sources/ebay.py` | `alerters/hardware/native/sources/ebay.py` unchanged | Preserve OAuth, query floors, seller trust, active/sold handling, variant identity and sample vetoes. Wrapped only to add explicit result-completeness metadata. |

The importer also copies every actual Python module under the original
`ada/sources/`, including its explicit factory. The bundle does not enumerate or
supply all their implementations. They are imported from the real checkout,
not reconstructed under guessed names.

## The supposedly shared layer

| Original responsibility | New home |
|---|---|
| `Verdict`, decision thresholds, `_decide`, domain assessment fields | Each plugin's judgment/configuration; bands are not renamed or mapped to a universal ladder. |
| `_ago` | `dealcore/verdict.py`; the evolved Steam version is authoritative. |
| `_fmt` | `dealcore/verdict.py::money`; Steam requests cents, hardware requests whole-dollar formatting at 100 and above. These were intentional presentation differences, not equivalent functions. |
| Threshold overlay and `.env` precedence | `dealcore/config.py`; dataclass defaults are the only threshold defaults. |
| Alert records, re-alert comparisons and serialization | `dealcore/state.py` plus `Improvement` in `dealcore/verdict.py`. |
| Hardware `_normalise_key` / `group_id` | `alerters/hardware/identity.py`, called identically for loaded state and live listings. Core knows keys, not eBay ID syntax. |
| Steam `TitleCache` | Steam source module. Its values are game metadata; no universal cache framework. Writes happen only in plugin persistence. |
| SMTP, ntfy, Discord, desktop execution | `dealcore/notify.py`; priorities and message content come from plugin cards. |
| Email-safe HTML and plain text | `dealcore/report.py`; Steam price bars and hardware model-ladder calculations stay in their plugins. |
| Both `check_deals.py` loops | `dealcore/run.py` and explicit registration in `alerters/__main__.py`. |
| Hardware `price_stats`, `evaluate`, `open_history`, `close_history` | Replaced by candidate preparation, history read/append and persistence methods in the hardware plugin. |
| Existing Actions state commits | New `.github/workflows/check.yml`. No original workflow body was supplied to preserve verbatim. |

## Import, then run

Run `python scripts/import_hardware.py ../ai-deal-alerter` once. It copies the real
domain implementations into this repository, rejects unexpected source shapes,
compiles the transformed files and records original SHA-256 hashes in
`alerters/hardware/native/MIGRATED.json`. It never changes the old checkout or
replaces an existing destination. Install the copied requirements before using
hardware; no new runtime framework is introduced.

The importer removes transport configuration and shared helper implementations
from the copied configuration/verdict modules. The full existing hardware
`Thresholds`, `Hunt`, matcher, history engine, catalog and rig comments remain.
Source implementations retain a compatibility import for the canonical `Listing`.
Neither the old run loop nor its state/report/notification modules are copied.

Copy the existing `watchlist.toml`, hardware configuration and durable JSONL/alert
state using the README commands. Do not copy `prices.db`; its unexported rows are
not the committed source of truth. If an old process has observations only in
SQLite, first finish its normal export before stopping that process and copying
JSONL. Stop the old cron before enabling the new one.

## Scar tissue retained

`loggable=False` from a source is an irreversible veto. Core may still display
and judge that listing but cannot append it, even if a plugin mistakenly returns
`loggable=True`. Deduplication combines vetoes conservatively. `multi_variant`
is retained separately and independently bars observation. It does not itself
bar an alert, matching the native judgment's distinction.

`group_id()` retains its original implementation and explanatory comment.
Variation options collapse for display and alert state; ordinary IDs remain
unchanged. Legacy keys are normalized during loading. Where old option keys
collide, preserve the most recent actual receipt per channel, not a fabricated
minimum-price/maximum-verdict record.

Condition hints override parsed title conditions exactly as before. Used, new
and refurbished are passed separately to native `History.stats`; the native
bucket mapping is not reimplemented. Both `min_observations` and
`min_observation_days` survive. Trustworthy sold-only statistics win; otherwise
the existing pooled fallback is retained. Sparse or short-span history still
uses native reference judgment and carries an explicit provisional warning.

All candidates read the pre-run evidence before any candidate is appended.
Source/matcher/judgment failures remain isolated. Hardware search windows do not
prove disappearance, so missing search hits do not erase suppression receipts.
A real relisting with a new listing ID is still a new opportunity; recycling the
same ID remains governed by improvement/reminder rules unless a future source
can explicitly prove removal. This is an intentional safety correction.

## Intentional changes, not claimed equivalence

The original hardware target promotion could raise a no-upgrade listing back to
STRONG after capping it at GOOD. The adapter re-caps it and sets a hard alert veto,
so even a lowered configured floor cannot ring a phone about an upgrade that
unlocks nothing. It remains visible under other observations.

Original hardware re-alerting requires a 4% drop; its 1.01-dollar constant is for
price/target equality, not that rule. Steam retains its strict drop greater than
0.011 and strict age-greater-than-reminder-days comparison. Neither policy is
silently substituted for the other.

A successful email or push transport gets its own receipt and its own price and
verdict baseline. Failed sends get none. A successful push is not evidence that
email arrived: “new” means new to that actual transport. Old aggregate push
receipts are conservatively imported into ntfy, Discord and desktop suppression.
Legacy files have only one shared price/band baseline and may contain receipts
for unsuccessful attempts. Import preserves the available record; it cannot
reconstruct discarded per-channel prices or infer which old sends actually arrived.
Independent, success-only receipts apply to new deliveries.

The old history docstring said “forever”; the supplied runner actually pruned at
730 days. This adapter retains the real 730-day daily policy. It does not prune
on fast runs or mutate history during dry runs/statistics.

Steam's original decision quirks are deliberately preserved for equivalence:
a recently ended cheap episode can still be classified as ongoing, and a
positive price compared with a genuine zero historic low raises division by
zero. The core isolates that assessment and reports an error rather than
silently inventing a new verdict. Those need a separate behavior-changing patch.

The value axis supplies explanatory context and the dollars-per-GB tiebreaker;
this port does not invent a weighted three-axis score. Native reference estimates
are capped at STRONG, which is not automatically below an arbitrarily configured
push floor (the supplied defaults also use STRONG). That comment/configuration
mismatch remains an explicit review point, not a claimed new safety guarantee.

Original fit enforcement, hunt quantity and maximum dollars-per-GB settings were
not applied by the supplied runner. This migration does not invent new effects
for them. Existing fit warnings and native capability calculations are retained.

## Verification boundary

The Steam implementation, workflow tests and hardware adapter contracts run
without the old repositories. The Steam verdict table was generated from the
verbatim original, not from the port; an environment variable enables direct
function-to-function comparison with that original during tests.

The hardware import transformations were compiled against the supplied verbatim
configuration and verdict modules. The omitted matcher, history, catalog, rig and
source implementations cannot be integration-tested from their signatures.
Hardware becomes executable after importing those real bodies and configuration;
its original regression suite should then be ported with relative import changes,
without replacing fixture expectations with outputs from the new adapter.
