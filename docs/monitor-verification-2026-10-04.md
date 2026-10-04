# Monitor review — October 4, 2026

This report records the pre-activation verification. The user subsequently
approved reduced-coverage activation and one test push after credential
provisioning. HP and anonymous community access remain unverified or blocked;
their limitations are not waived by that approval.

## Checkout and preserved behavior

- Initial checkout was clean at `1091b05`, matching fetched `origin/main`.
- Main later advanced to `aaf2848` with only a Steam receipt update. That update
  was fast-forwarded while retaining all implementation changes.
- The RTX 5090 target remains **$5,000**, and the gaming-PC search is unchanged.
- Existing hardware price history and notification receipts have no local diff.
- Existing prebuilt target qualification, same-condition 5% undercut promotion,
  ntfy transport and successful-delivery receipts are reused.
- Live GitHub switches remain `ENABLE_HARDWARE=true`,
  `ENABLE_HARDWARE_FAST=true`, `ENABLE_STEAM=true`. No live schedules changed.

## Verification

The Windows Python 3.11 suite passed: **928 tests and 58 subtests**. The baseline
was 871 tests. Coverage added for coupon/accessory/shipping arithmetic, priority
boundaries, selected-GPU conflicts, seller changes, missing/placeholder prices,
unknown stock, separate new/open-box/refurb history, dry-run immutability,
successful/failed delivery receipts, meaningful price changes, repeated restocks,
price-less announcements, Pacific/DST start times, due rechecks, rate limits and
persisted cooldowns, concurrent fetches, stale monitoring and OS writer locks.

Both generated task XML files passed Windows Task Scheduler's
[validate-only API](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertask).
Neither task is registered. The preparation script was executed successfully;
the cutover/enable script was syntax-checked but **not executed**. Actual SYSTEM
startup, reboot recovery, delivery and battery/wake behavior remain post-approval
acceptance checks. AC sleep timeout is currently zero (never); battery sleep is
20 minutes. No power settings were changed.

The live dry run at approximately **2:53 PM PDT** returned exit 1 to make partial
coverage visible. It wrote only local diagnostic files and HTML previews.

| Source | Verified result |
| --- | --- |
| Newegg selected Skytech product | Parsed exact desktop RTX 5090, selected GPU 5090, Core Ultra 9 285K, 64GB DDR5, 2TB SSD, 1200W PSU, new, Skytech seller A1HJ, in stock, $7,599.99 plus $0 shipping at the time checked. Above target; no push. |
| Newegg discovery | Both public discovery jobs succeeded; 22 unique Newegg product URLs were retained, including the seed. One-shot mode verified the seed product, not every discovered URL. No ABS product was independently confirmed in this dry run. |
| HP OMEN | Local HTTP read timeout; retries backed off. The fixed-SKU parser passes fixture tests but is **not live validated**. Dynamic/custom base configurations are deliberately unconfirmed. |
| Reddit | Anonymous RSS path disallowed by current robots policy. Credentialed API support is implemented; local credentials are absent, so it was not exercised live. |
| Slickdeals | Search RSS path disallowed by current robots policy. The forums RSS endpoint redirected to that blocked search path. No bypass was attempted. |
| Apple refurb | Existing source succeeded with zero relevant listings. |
| eBay | Disabled locally because credentials are absent; existing GitHub credentials remain configured. |

The observed Newegg price is a timestamped parser check, not a recommendation or
a promise of current stock. Official access policies can be inspected at
[HP robots.txt](https://www.hp.com/robots.txt),
[Newegg robots.txt](https://www.newegg.com/robots.txt),
[Reddit robots.txt](https://www.reddit.com/robots.txt) and
[Slickdeals robots.txt](https://slickdeals.net/robots.txt).

Local artifacts:

- `.local/verified-dry-run/health.json`: per-source results and next retries.
- `.local/verified-dry-run/previews/`: actual dry-run reports.
- `.local/review/confirmed-example.html`: clearly labelled **synthetic** example
  showing coupon + accessory arithmetic and highest priority.
- `.local/review/announcement-example.html`: clearly labelled **synthetic**
  price-less upcoming-sale notice with a Pacific start time.
- `.local/windows/`: hashed release, two task XML files and a secret-name template.

## Credentials and cutover decision

Only presence/names were inspected. No secret values were displayed or copied.
GitHub secret names include ntfy topic, eBay credentials and SMTP credentials.
No corresponding local process/user/machine variables or expected local
credential files were found. GitHub cannot reveal those saved values for reuse.

Keep this staged until HP/community access and local credentials are resolved,
or explicitly approve a reduced-coverage deployment. An enabled monitor can
send ordinary qualifying offers and health warnings. A test push is a separate
approval. No push was sent during this work, no background service was enabled,
and no purchase or paid infrastructure was created.

The concrete [cutover and rollback procedure](thinkpad-monitor.md#cutover-checklist--requires-approval)
disables and drains both GitHub hardware schedules, snapshots current hardware
state, creates the single local writer and preserves Steam scheduling. The
installer requires the reviewed ownership guard to be on `origin/main`, an
unchanged tested release, local credentials and explicit `-ApproveCutover`.
