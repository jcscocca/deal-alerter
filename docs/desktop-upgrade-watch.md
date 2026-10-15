# Desktop purchase watch: factory 32/64GB plus the owned 64GB kit

As of October 14, 2026, the user supplied a completed MSI/9950X3D desktop with
128GB DDR5, an internal RTX 5090 and a separately powered OCuLink RTX 5070 Ti.
`config/desktop-inventory.toml` records the build and remaining uncertainties.
The Corsair pair is allocated to that build. The user requested a small
extension of existing watches: additional high-end 50-series cards, especially
immediate 5090 notifications, desktop 96GB (2x48GB) UDIMM kits and single 64GB
UDIMMs. The earlier prebuilt reuse strategy below remains configured; it is
historical purchase logic rather than the current inventory.

New-card ceilings are $1,000 for 5070 Ti (existing), $1,500 for 5080
(provisional), and $5,000 for 5090 (existing). All qualifying 5090 card notices
use push priority 5. The 5080 target/standout prices are $1,400/$1,300; 5090
$4,500/$4,000. Desktop memory notices use $1,109.99 for a complete
2x48GB kit and $937.49 for a single 64GB module. The original $600/$400 guesses
were replaced after the user's benchmark review on October 14. These are
editable alert settings, not asserted sold values or purchase budgets. Two 96GB kits may
provide 192GB, but their combined compatibility and speed require validation.
MSI publishes four DDR5 UDIMM slots and a 256GB maximum for the PRO B840-VC WIFI:
https://www.msi.com/Motherboard/PRO-B840-VC-WIFI/Specification

`config/desktop-memory-market.toml` preserves the dated reference quotes and
their stock/shipping limitations. Newegg's selected new offers showed Add to
cart at $1,249.99 for Kingston KF556C36BBEA-64 and $1,479.99 for G.SKILL
F5-5600J4040D48GX2-RM5RW. At the user's request, the alert limits apply a 25%
reduction, rounded down to cents. These are a small sample of retail asks, not market-wide
medians or sold-price evidence. CDW's $1,209.99 single-module quote had no
confirmed delivery/stock evidence; Corsair's $1,421.99 96GB kit and Newegg's
$1,449.99 Flare X5 kit were sold out, so they were recorded as context rather
than selected in-stock references. No speed or RGB premium is inferred.

- https://www.newegg.com/p/0RN-001J-015E9?Item=0RN-001J-015E9&SoldByNewegg=1
- https://www.newegg.com/p/N82E16820374549?Item=N82E16820374549&SoldByNewegg=1

The card notices retain condition, identity, seller and bait-price checks.
eBay sorted asks stay excluded from market history; explicit watches can
notify only after an exact-item lookup confirms identity, delivered price and
stock. The existing bounded lookup budget and source backoff also apply to
these checks. Other card discovery remains through the existing community
feeds; this does not add direct GPU-store polling. A checkout change requires
the existing release procedure before the installed monitor uses it.

The desktop profile extends the existing ThinkPad monitor and uses the same
notification delivery, deduplication, offer history and source health reports.
The implementation is in the checkout; deploying it to the installed runtime
is a separate release step. It does not create another scheduled writer.

## Buying strategy

Compare two routes before buying:

1. A 5080/5090 prebuilt with four DDR5 slots and only two occupied. A factory
   2x32GB configuration plus the owned pair could provide 128GB; factory 2x16GB
   plus the owned pair could provide 96GB. Neither combination is guaranteed.
2. Upgrade the existing desktop. The recorded inventory is an i7-14700,
   Z790 AORUS PRO X and EVGA SuperNOVA 1000 GT, with RTX 3080 and RTX 2080 cards.
   Confirm that inventory and case clearance before comparing GPU plus RAM
   costs. Replacing the old cards and keeping them installed are different
   power budgets. This route remains a manual comparison in this version;
   there is no new component-bundle alert claiming a complete upgrade price.

The owned RAM is Corsair Vengeance RGB CMH64GX5M2B6000C40W, 64GB (2x32GB),
DDR5-6000 CL40 Intel XMP. Its specified default speed is 4800; reaching 6000
depends on the CPU, board and BIOS. Four modules and mixed kits may require
lower speeds or fail stability testing. Physical slots and a maximum-capacity
specification are not validation of a mixed memory configuration.

References:
- [Corsair kit specifications](https://www.corsair.com/us/en/p/memory/cmh64gx5m2b6000c40w/vengeance-rgb-64gb-2x32gb-ddr5-dram-6000mt-s-cl40-memory-kit-white-cmh64gx5m2b6000c40w)
- [Corsair guidance on mixing kits](https://www.corsair.com/us/en/explorer/diy-builder/memory/can-i-mix-corsair-memory-kits/)
- [Z790 AORUS PRO X specifications](https://www.gigabyte.com/us/Motherboard/Z790-AORUS-PRO-X/sp)

## Alert rules

`config/desktop-profile.toml` records the RAM and price preferences. The user
selected inclusion of promising deals whose RAM compatibility still needs
verification. This watch only considers factory **32GB or 64GB** configurations.
Factory 96GB/128GB systems are excluded. Unknown capacity can surface for review;
it is not assumed to be either supported configuration.

Provisional 5080 notification settings, calibrated to the checked listings below:

| Factory RAM | Potential total with owned kit | Highest priority | High priority | Normal watch range |
| --- | --- | --- | --- | --- |
| 32GB (2x16GB) | 96GB | Up to $2,500 | Through $2,800 | Through $3,000 |
| 64GB (2x32GB) | 128GB | Up to $2,980 | Through $3,280 | Through $3,480 |

These are editable alert settings, not user-approved spending limits, proven
market floors or predictions of future sales. The bands price a reference build
(32GB, 1TB SSD, 9800X3D-class CPU). Since October 13, 2026, `[components]` in
`config/desktop-profile.toml` shifts all three thresholds by the value of the
parts that differ: RAM and SSD at retail per GB/TB, the CPU at used resale
against the 9800X3D. The 64GB row above assumes no storage or CPU difference.
Missing storage or CPU earns no credit. Unknown installed capacity is valued as
64GB at normal priority. Each card shows the base and every adjustment.

Manually checked in the browser on October 6, 2026 (prices before tax):

- [HP OMEN 35L GT16-1085m](https://www.hp.com/us-en/shop/pdp/omen-35l-gaming-desktop-gt16-1085m-pc):
  $2,799.99, 9800X3D/5080, 32GB (2x16GB), four DIMM slots, 2TB; Add to cart shown.
- [PowerSpec G913](https://www.microcenter.com/product/700439/powerspec-g913-gaming-pc):
  $3,799.99, 9900X3D/5080, 64GB, four slots, 2TB. Pickup only; store stock and
  factory stick count still need checking.
- [Skytech Azure 3](https://www.newegg.com/p/3D5-000Z-003H2?Item=9SIA1HJKP24777):
  $3,999.99, 9800X3D/5080, 64GB, 4TB; sold/shipped by Skytech, free shipping,
  Add to cart shown. Board model, stick count and free DIMM slots unverified.
- [MSI Vision ZS 9NVV-1275US](https://www.microcenter.com/product/690535/msi-vision-zs-9nvv-1275us-gaming-pc):
  useful layout example with 64GB (2x32GB), four slots/two free and a 256GB maximum.
  No current price or shipping availability established; not an orderable deal.

The 32GB and 64GB examples have other specification differences. Their price gap
does not establish the cost of RAM alone. All mixed-kit compatibility remains unverified.

The 5090 ceiling remains the existing $5,000 watchlist target with its original
priority bands. Existing fresh same-condition loose-GPU undercut promotion can
still qualify an above-target PC. All prices include known shipping and required
accessories, less confirmed eligible coupons. They exclude tax and uncertain
cashback. Reuse assumes adding the already-owned kit. Unknown necessary costs prevent a
confirmed PC total; an unverified announcement is always labeled separately.

Each alert has a separate RAM status:

- **POSSIBLE REUSE:** DDR5, two installed modules, four slots and the capacity
  ceiling are documented. Adding the owned pair mathematically reaches 96GB
  or 128GB. Mixed-kit stability and speed remain unverified.
- **NEEDS SPECS:** Missing or conflicting specifications. A promising price
  may still notify; it is never labeled as a confirmed RAM upgrade.
- **NO REUSE PATH:** Explicit DDR4, a board without four slots, inadequate
  maximum capacity, or a layout other than two occupied/two free slots. No specialized push.
- **OUTSIDE REUSE WATCH:** Factory capacity other than 32GB or 64GB. No specialized push.

Unknown details do not become zero, and GPU VRAM is never counted as system RAM.
Exact-SKU reviews can fill missing layout fields; conflicts require a new review.
An exact-SKU review must cite its source and review date. It does not validate
mixing the owned kit with whatever memory the vendor happens to ship.

The price comparison is between 32GB and 64GB prebuilts using the owned kit.
Do not add new 96GB/128GB kits or factory 96GB/128GB prebuilts to this watch.
Do not subtract hypothetical resale proceeds. Disabling `allow_unverified`
suppresses reuse alerts because physical layout alone cannot validate mixing kits.

## Coverage and operation

The fast adapters now distinguish RTX 5080 from RTX 5090 in the selected
configuration. Newegg discovery supports ABS, Skytech, CyberPowerPC, iBUYPOWER,
MSI, Gigabyte, Stormcraft and HP. The seller trust rules remain Newegg itself
and the verified Skytech store; merely listing a brand does not trust every seller.
HP remains fixed-SKU OMEN only. Dynamic/cart-dependent prices remain unconfirmed.
The October 7 source expansion adds fixed CyberPowerPC and Skytech direct
products at ten-minute intervals. Skytech's public SKU sitemap refreshes every
six hours. iBUYPOWER's fifteen-minute RDY catalog check provides unverified
quotes only. Missing or contradictory stock, shipping or condition evidence
cannot trigger inventory alerts or enter current-price comparisons.

Added the HP 35L and Skytech Azure 3 fixed offers, general price-sorted Newegg
5080 discovery and a separate 64GB discovery page. The total
per-retailer product cap is 48; reaching the cap is reported as a coverage gap.
The existing target cadences remain 2 minutes for products, 5 for community
feeds and 10 for discovery, subject to failures, robots rules and backoff.

Observed on October 6: the installed monitor was checking Newegg and Slickdeals;
HP requests were failing and Reddit was disallowed by robots.txt. Best Buy and
Micro Center still depend on discovery posts/manual review. Walmart now has a
separate [on-demand TechScout report](techscout-shopping.md) using signed API
search and ZIP-specific lookups; it does not feed the live monitor or alerts.
Its desktop mode applies this same RAM reuse profile. This does not cover the
entire market. Native store restock alerts and manual searches remain useful
complements.
Best Buy remains deferred because the earlier API signup required an eligible
email domain and no key was obtained. B&H and Adorama returned HTTP 403 during
the October 7 access checks; Costco is omitted by preference. The dashboard's
existing publisher feeds now accept tech reports across retailers, separately
from confirmed direct inventory.

## Preview, tests and release

```powershell
.\.venv\Scripts\python.exe scripts\preview_desktop_profile.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_desktop_profile.py tests\test_prebuilt_monitor.py
.\.venv\Scripts\python.exe -m alerters.hardware.monitor --once --dry-run --runtime .local\desktop-watch-dry-run
```

The preview is explicitly simulated, uses isolated temporary state and sends
nothing. The live dry run also sends nothing and preserves live history.
Review source coverage separately from unit-test success.

The installed monitor runs from `C:\ProgramData\DealAlerter\app`, so editing this
checkout does not activate the profile. Use the existing prepared, clean merged
release procedure in `scripts/windows/Update-Monitor.ps1`; do not copy files into
the running writer or create a competing scheduler.
