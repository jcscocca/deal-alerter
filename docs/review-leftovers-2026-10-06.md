# Earlier review follow-up — October 6, 2026

The repository audit found no open PRs or unresolved GitHub review threads.
The earlier PR descriptions still named two code/catalog gaps, addressed here:

- PR #18's `NVIDIA RTX A6000 GPU Server Graphics Card` now resolves as a
  standalone card. The model must precede `GPU Server`, immediately followed
  by the card description. Server-first titles, CPU/RAM/storage, server brands
  and multiple GPUs retain their whole-machine classification.
- PR #23's W7800 catalog follow-up now distinguishes the 32GB and 48GB cards.
  Both require one explicit VRAM capacity; unknown, conflicting or system-RAM-only
  capacities cannot choose a variant. The existing 32GB key is preserved.

[AMD's specification table](https://www.amd.com/en/products/specifications/professional-graphics.html)
lists the 48GB model at 864 GB/s and 260W, versus 576 GB/s for the 32GB model.
[Gigabyte's announcement](https://www.gigabyte.com/uk/press/news/2238) establishes
the 48G product name and November 2024 availability. Vendor cooler dimensions
and board power can vary; the new entry does not promise a slot fit. Its $1,800
reference is an explicitly unverified placeholder carried from the existing
family estimate, not a newly researched sale price or buying recommendation.
Regression coverage verifies that neither estimate can promote a target hit.

Replaying all 1,765 unique titles in the 3,778-row live price history changed no
existing classifications. All 67 W7800 observations retain their stated 32GB
identity. The older audited bad rows are corrected or absent, and the 564
titleless observations remain archived outside price baselines. No history
migration is required for these changes.

Local validation: 1,292 tests and 58 subtests passed, including the new
classification, capacity-selection and unverified-price-reference cases.

Operational acceptance remains separate:

- The installed monitor was still at PR #47 during this check. Merged TechScout
  controls, alert history and Windows shortcuts await the protected upgrade.
- A fresh Edge HP probe again returned `HP headless browser unavailable or
  navigation failed`. Keep the optional browser reader disabled; issue #36
  stays open. Reddit's documented access limitation is unchanged; no new API
  credential request is pending. Slickdeals category discovery remains partial.
- The live eBay EXTENDED-description acceptance check could not read the
  SYSTEM-protected credentials as the normal user. Offline adapter tests still
  cover descriptions and their absence; a live acceptance result is pending.
- Physical boot/network recovery remains tracked in issue #37. There is no
  recovery-result receipt yet. An external dead-host check remains optional.

These checks sent no test notifications, changed no source-access policy, and
did not restart the monitor or interrupt networking.
