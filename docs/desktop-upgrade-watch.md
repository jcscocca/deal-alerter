# Desktop purchase watch: factory 32/64GB plus the owned 64GB kit

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
| 64GB (2x32GB) | 128GB | Up to $3,300 | Through $3,600 | Through $4,000 |

These are editable alert settings, not user-approved spending limits, proven
market floors or predictions of future sales. Unknown installed capacity uses
the wider $4,000 limit at normal priority. The two tiers are not interchangeable.

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
