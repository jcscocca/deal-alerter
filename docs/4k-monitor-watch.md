# 27-inch 4K monitor deal watches

The requested display is 27-inch class, native 3840x2160, at least 144Hz at
that resolution, and has a separate DisplayPort input. OLED is optional.
Panels marketed as 27-inch sometimes measure 26.5 or 26.7 inches; those count
as the same size class. A 28/32-inch display, 1440p OLED, 120Hz 4K monitor,
or a screen with only HDMI/USB-C does not qualify. USB-C DP Alt Mode alone
does not establish the required DisplayPort input.

`config/monitor-watch.toml` owns the requirements, documented models, ports,
and price limits. The initial limits carry over the 25% discount preference:

| Watch | Representative retail benchmark | Alert ceiling |
| --- | --- | --- |
| Standard panel / panel not specified | Alienware AW2725QF: $399.99 | $299.99 |
| OLED | Alienware AW2725Q: $799.99 | $599.99 |

Both benchmarks were read from Dell's US product pages on October 14, 2026;
their source URLs are saved in the configuration. Use the current selling
price, rather than Dell's higher “Estimated Value.” Shipping, tax and delivery
were not checked. These are representative purchase limits, not proof that a
particular model is 25% off, a sold-price valuation, or an absolute purchase
budget supplied by the user. Benchmarks are manually maintained; they do not
automatically follow later price changes. Cents round down.

The documented models are Alienware AW2725QF and AW2725Q, ASUS XG27UCS,
MSI MAG 274UPF E2 and MPG 272URX, and LG 27GR93U-B. Each has a manufacturer
specification source. Exact model identification can supply omitted size,
native resolution, refresh rate and ports, even if the title only names the
model. Explicit contradictory size/resolution/speed or broken DisplayPort
evidence prevents an alert. Known dual-mode models use their 4K refresh rate,
not the faster 1080p mode. These spec records do not assert current stock.

Other brands/models can qualify when the title explicitly states the required
size, 4K resolution, refresh rate and DisplayPort input. An unknown product
with missing or ambiguous specs stays out. A panel whose type is unstated
uses the lower standard ceiling and does not claim to be LCD or OLED.
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
USD price, known shipping and purchasable stock. Verification must be no more
than 20 minutes old. Item lookups share the existing 20-request budget and
rate-limit handling with RAM/cards; a deferred lookup cannot alert.

Each alert has one `Ports:` fact, e.g. `DP 1.4; 2x HDMI 2.1; USB hub`.
Shopping cards show the same information in the existing small specification
strip. USB-C charging, hub and video capabilities are distinguished where the
manufacturer documents them. Monitor categories never enter the hardware
market-price log: mixing different models would create misleading percentiles.
Existing delivery receipts still suppress repeats.

The change takes effect after the usual reviewed merge and ThinkPad upgrade
in `docs/thinkpad-monitor.md`. Preparing code locally does not update the live
service, scheduled tasks or notification subscriptions.
