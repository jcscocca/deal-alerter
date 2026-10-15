# 27-inch 4K monitor deal watches

The requested display is 27-inch class, native 3840x2160, at least 144Hz at
that resolution, and has a separate DisplayPort input. OLED is optional.
Panels marketed as 27-inch sometimes measure 26.5 or 26.7 inches; those count
as the same size class. A 28/32-inch display, 1440p OLED, 120Hz 4K monitor,
or a screen with only HDMI/USB-C does not qualify. USB-C DP Alt Mode alone
does not establish the required DisplayPort input.

`config/monitor-watch.toml` owns the requirements, documented models, ports,
and exact-model benchmarks. Alerts require at least 25% below the recorded
retail quote for that specific model:

| Model | Recorded retail benchmark | Alert ceiling |
| --- | --- | --- |
| Alienware AW2725QF | $399.99 | $299.99 |
| Alienware AW2725Q | $799.99 | $599.99 |
| ASUS XG27UCS | $399.00 | $299.25 |
| MSI MPG 272URX | $899.99 | $674.99 |
| MSI MAG 274UPF E2 / LG 27GR93U-B | No verified current purchasable US quote | Alerts withheld |

Quotes were checked on October 14, 2026 against the Dell, ASUS and MSI US
product/store pages linked in the configuration. Use the quoted selling
price, rather than MSRP or Dell's higher “Estimated Value.” The MSI MAG page
is out of stock; LG's accessible product page does not give a current price.
Their specs remain recognized but they cannot inherit another model's limit.
Benchmarks are manually maintained and do not automatically follow later
price changes. The alert quotes its model's benchmark and check date, so the
discount is explicitly against that recorded quote, not a live market-price
claim or sold-price valuation. Cents round down; tax is excluded.

The documented models are Alienware AW2725QF and AW2725Q, ASUS XG27UCS,
MSI MAG 274UPF E2 and MPG 272URX, and LG 27GR93U-B. Each has a manufacturer
specification source. Exact model identification can supply omitted size,
native resolution, refresh rate and ports, even if the title only names the
model. Explicit contradictory size/resolution/speed or broken DisplayPort
evidence prevents an alert. Known dual-mode models use their 4K refresh rate,
not the faster 1080p mode. These spec records do not assert current stock.

Other brands/models can be recognized when the title explicitly states the
required size, 4K resolution, refresh rate and DisplayPort input. An unknown
product with missing or ambiguous specs stays out. Recognized products with
no exact model and recorded benchmark cannot send discount alerts. A panel
whose type is unstated does not claim to be LCD or OLED.
Accessories, broken panels, multiple-model menus, whole-PC bundles and lots
do not qualify. New condition is required; used/open-box/refurbished listings
do not inherit new-monitor price limits. Conditional rebate, cashback,
trade-in and installment amounts do not trigger alerts.

The watch uses existing eBay, Slickdeals and r/buildapcsales sources and their
current schedule. Two extra broad searches cover displays without displacing
existing GPU or RAM queries (34 searches, cap 36). Amazon/Best Buy and other
retailers are seen through community deal posts; this change does not add a
direct poller for each store.

Community pushes say **COMMUNITY LEAD** and state that retailer stock, shipping
and checkout are unverified. An eBay search hit alone cannot alert: an exact
item lookup must confirm its current identity, new condition, seller, fixed
USD price, known shipping and purchasable stock. The model must agree between
the search and exact item, and negative search descriptions remain available
to veto broken ports, excluded screens and conditional prices. Verification must be no more
than 20 minutes old. Item lookups share the existing 20-request budget and
rate-limit handling with RAM/cards; a deferred lookup cannot alert.

Each alert has one `Ports:` fact, e.g. `DP 1.4; 2x HDMI 2.1; USB hub`.
eBay alerts also show the stock-check time, and saved delivery activity keeps
the availability evidence for later audits.
Shopping cards show the same information in the existing small specification
strip. USB-C charging, hub and video capabilities are distinguished where the
manufacturer documents them. Monitor categories never enter the hardware
market-price log: mixing different models would create misleading percentiles.
Existing delivery receipts still suppress repeats.

The change takes effect after the usual reviewed merge and ThinkPad upgrade
in `docs/thinkpad-monitor.md`. Preparing code locally does not update the live
service, scheduled tasks or notification subscriptions.
