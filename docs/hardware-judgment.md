# How hardware listings are judged

Carried over from `ai-deal-alerter`'s README when it was retired. Every rule
here came from a real listing seen while building the matcher.

## What it filters out

| Listing | Problem |
|---|---|
| `Acer Predator Helios AI: 16" QHD+ 240Hz, RTX 5090` | Laptop. The mobile 5090 is *different silicon* -- 24GB, half the power. Rejected outright, not just flagged |
| `HP Omen 45L ... RTX 5090, 64GB RAM, 2TB SSD` | Prebuilt. Never says "desktop"; detected by CPU and storage. Shown, never logged as a GPU price |
| `Seasonic Focus GX 850W PSU \| PCIe 5.1 \| RTX 5080 &...` | A PSU naming a GPU for compatibility |
| `Lot of 6 RTX 3090 mining rig - $3600` | Six cards at $600 each. Scored per unit; read as one card it looks terrible and gets discarded |
| `RTX 3090 *BOX ONLY*` | Cardboard |
| `Apple Mac Studio (Early 2025) Desktop Computer $1699` | No stated memory. Ambiguous between a 96GB and a 512GB, and the matcher refuses to guess |
| `[USA-MI][H] Local cash, PayPal [W] RTX 5090` | Someone **buying** a 5090, not selling one. Three of seven GPU posts sampled on r/hardwareswap were purchase requests |
| `[USA-TX] [H] Gigabyte 4090, 3090 FE, 32gb DDR5, 1TB NVME [W]` | Bundle: four items, one post, prices scattered through the body. Shown, never logged |

## What it refuses to learn from

Being shown a listing and recording its price are separate decisions, and the
second bar is higher. You can look at a dubious listing and dismiss it in thirty
seconds; the log cannot, and a bad price in it skews every future verdict for
that part. So these are surfaced with the reason stated, and never recorded:

| Listing | Why it isn't evidence |
|---|---|
| Anything from eBay's active search | Sorted by price ascending, so it is the 50 *cheapest* listings per query -- the right slice to hunt in, the wrong one to measure from. Logging it would build a distribution of the cheap tail and make genuinely good prices look ordinary |
| Far below the reference price | The band real scams live in, because bait has to be believable -- and exactly where a genuine steal lives too. Price alone cannot separate them, so you are shown both and the log stays clean. `suspicious_price_ratio` in `config/hardware.toml` sets the line |
| A seller with almost no feedback, poor feedback, or a mismatched origin | None of these is proof; together they are the standard profile. One level down rather than rejected, since every honest seller starts at zero feedback -- unless the price is also suspiciously good, which is one profile rather than two discounts, and falls clear of the alert floor |
| For-parts or not working | Already scored PASS, but its price would otherwise land in the `used` bucket and become the all-time low for working cards |

Sold prices and asking prices do not pool either. An asking price is what nobody
has paid yet; once a part has enough confirmed sales, those become what it is
judged against, and asking prices stop diluting them.
