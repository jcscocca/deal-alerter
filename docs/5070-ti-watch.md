# RTX 5070 Ti alerts

Added at the user's request on October 10, 2026. These editable notification
settings are not spending approval or predictions of holiday prices.

| Listing | Alert through | High priority | Highest priority |
| --- | ---: | ---: | ---: |
| New desktop card | $1,000 | $950 | $900 |
| Factory 32GB prebuilt | $2,200 | $2,100 | $2,000 |
| Factory 64GB prebuilt | $2,400 | $2,300 | $2,200 |

The $900 card price is a standout stretch deal. Current retail was $1,169.99
at Newegg when checked. September 32GB prebuilt sales at $1,899 and $1,999
were expired; the wider watch limits allow useful discounts above those lows.
Prices exclude tax. Prebuilt limits include known shipping and required costs.
Card listings use the existing source price evidence and require checkout and
Seattle delivery verification; community posts do not prove current inventory.

The existing hardware monitor handles delivery and deduplication. Card discovery
uses its eBay searches and community feeds. A new-card price notice explicitly
opts into price alerts independently of the native model-capacity recommendation;
it does not fabricate sold-price evidence or lift the card's native grade.
Used/refurbished/open-box cards, risky sellers, variants, accessories, bundles,
nonworking cards and source-vetoed listings cannot use this notification route.

Prebuilts use the existing 32GB/64GB RAM-reuse profile, including its explicit
unknown-specification notices. Factory 96GB/128GB and known incompatible layouts
remain excluded. GPU VRAM is separate from system RAM; mixed-kit stability is
unverified. Unknown factory RAM uses the $2,400 ceiling at normal priority.

Newegg has separate 5070 Ti and 64GB discovery searches plus the Yeyian Phoenix
9800X3D/32GB/2TB SKU N82E16883630088 as a fixed seed. Yeyian brand support does
not expand seller trust: only the existing trusted seller rules qualify.
CyberPowerPC, Skytech and iBUYPOWER discovery now recognizes desktop 5070 Ti
configurations, with each source's existing confirmation limits. Walmart remains
on-demand research, outside live alert delivery. Existing 5080/5090 settings stay
unchanged. The product cap increases from 48 to 64 per retailer to leave room
for the new GPU alongside existing products, retaining host throttling and
backoff. Retailer access failures and product caps still limit coverage.

Settings: `config/watchlist.toml`, `config/desktop-profile.toml`,
`config/monitor.toml`. Deploy using the existing prepared-release procedure.
