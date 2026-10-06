# HP browser reader development evidence — October 6, 2026

The optional reader is implemented and disabled by default. It is not a live
coverage restoration, and does not close issue #36.

## Observed public evidence

The interactive Codex browser loaded the fixed selected products after hydration:

- [GT22-3090, B91WJAA#ABA](https://www.hp.com/us-en/shop/pdp/omen-by-hp-45l-gaming-desktop-gt22-3090-b91wjaa-aba):
  RTX 5090, $6,999.99, out of stock.
- [GT23-0990m, CK4N6AA#ABA](https://www.hp.com/us-en/shop/pdp/omen-max-45l-gaming-dt-gt23-0990m-pc-ck4n6aa-aba):
  RTX 5090, $8,099.99, enabled Add to cart and an arrival estimate.

These are point-in-time observations, not current buying recommendations or
unattended health receipts. Initial HTML had a blank price; the rendered primary
Product/Offer schema and visible purchase section eventually agreed. The reduced
CK4N6AA fixture retains the actual selectors/schema shape and normalizes whitespace.
Tests derive stale, conflicting, configurable and out-of-stock variants from it.

## Unattended result

Playwright 1.63.0 with fresh installed Edge and Chrome sessions, their default
browser identities, and browser sandbox enabled failed navigation with
`net::ERR_HTTP2_PROTOCOL_ERROR`. A diagnostic with HTTP/2 disabled timed out.
That diagnostic flag is not part of the implementation. A plain HTTP request
also timed out. We have not established the server's reason for the different
interactive and headless behavior.

The implemented `--probe` on fresh Edge returned exit 1 with:

```json
{"status": "unavailable", "reason": "HP headless browser unavailable or navigation failed"}
```

No personal profile, cookies, alternate IP, stealth modification or challenge
bypass was used. No live service dependency/configuration or task was changed.

## Validation and remaining gate

Tests cover agreement of visible SKU/price/stock with selected schema, placeholder
and accessory rejection, scoped discovery, robots and request restrictions,
shared cooldown, other-source isolation, sanitized worker errors/environment,
timeout cleanup, real process termination and opt-in monitor routing. A real
headless Edge test hydrates the saved fixture through intercepted requests;
it exercises browser startup, navigation, delayed rendering and teardown without
contacting HP. That test proves the implementation can render, not HP access.

The next acceptance gate is successful repeated **fresh headless** live probes,
including category discovery with the existing first-party/robots restrictions,
followed by SYSTEM-context verification. Until then leave the production switch
off and preserve HP's degraded status. Supported browser channels follow
[Playwright's browser documentation](https://playwright.dev/python/docs/browsers).
