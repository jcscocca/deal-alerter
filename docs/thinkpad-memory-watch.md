# ThinkPad memory watches

Added 2026-10-10 at the user's request for both spare/replacement 32GB modules
and larger 48GB modules. The ThinkPad P16 Gen 2 (21FA0052US) currently has four
32GB DDR5-5600 SO-DIMMs, running at 3600 MT/s. All four slots are occupied.

User-selected limits in `config/watchlist.toml`:

| Purchase | Alert at or below |
| --- | ---: |
| One 32GB DDR5 SO-DIMM | $200 |
| One 48GB DDR5 SO-DIMM | $300 |
| 64GB kit, 2x32GB | $400 total |
| 96GB kit, 2x48GB | $600 total |

These are listed-price notices, not sold-price valuations or guaranteed good
buys. Known shipping is included by the source; missing shipping and checkout
eligibility still need checking. New, used, open-box and refurbished listings
can qualify. Unknown condition, risky sellers, unavailable/sold items, broken
parts, variant menus and ambiguous module counts cannot. Per-module prices
advertised in a kit title cannot qualify as the whole kit's price. Kits are one
purchase: a $600 2x48GB kit is never recorded or displayed as a $300 kit.

The monitor searches these four layouts through its existing eBay searches
and community feeds. Retailer coverage through those feeds is indirect; this
does not add continuous Amazon, Walmart or Newegg memory scraping. The Memory
tab's on-demand Walmart searches now include SO-DIMMs as well as desktop kits.
Memory results with “laptop memory” titles stay under Memory. Generic brands
need explicit DDR5 SO-DIMM and capacity evidence; known Crucial/Kingston model
numbers can resolve omitted wording. Different brands are not pooled into a
claimed market-value history. Existing notification receipts handle repeated
listings and meaningful price drops.

[Lenovo PSREF](https://psref.lenovo.com/WDProduct/ThinkPad/ThinkPad_P16_Gen_2)
documents four SO-DIMM slots, up to 192GB non-ECC with 4x48GB, and 3600 MT/s for
4x32GB / 4x48GB configurations. Buying more 32GB sticks replaces existing RAM;
it does not increase capacity. Buying one 96GB kit is only two modules, not the
entire 192GB upgrade. Verify the exact module, BIOS support and mixed-kit
stability before purchase; alerts do not certify compatibility.

[Kingston's compatibility list](https://www.kingston.com/unitedkingdom/en/memory/search/model/107826/lenovo-thinkpad-p16-gen-2)
includes KCP556SD8-32 and KCP556SD8-48. Crucial examples are CT32G56C46S5,
CT48G56C46S5 and their CT2K two-module kit equivalents. Desktop UDIMMs,
registered/server DIMMs, DDR4, ECC modules and CAMM modules are excluded from
these non-ECC SO-DIMM watches. DDR5 on-die ECC is not system-level ECC.
