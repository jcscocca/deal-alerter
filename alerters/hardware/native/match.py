"""Turning a messy listing title into a catalog part, a price and a condition.

A Steam wishlist hands you an appid. Nothing here does. What you get instead is

    [GPU] EVGA GeForce RTX 3090 FTW3 Ultra Gaming - $749.99 (eBay)
    RTX 3090 *BOX ONLY* no card - $25
    NVIDIA RTX A6000 48GB -- FOR PARTS, NOT WORKING

and you have to work out that the first is a real 3090, the second is cardboard
and the third is e-waste. Getting this wrong in the permissive direction means
a push notification for a cardboard box; getting it wrong in the strict
direction means missing the deal you built the tool for. So the junk filter runs
before matching, and matching prefers the most specific alias that fits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import PARTS, Part

# Phrases that mean the listing is not the thing itself. Checked first, because
# "RTX 3090 box only" matches the 3090 aliases perfectly well.
JUNK_PATTERNS = (
    r"\bbox(?:\s+only)?\b(?!\s*(?:art|ed))",
    r"\bempty\s+box\b",
    r"\bfor\s+parts\b",
    r"\bnot\s+working\b",
    r"\bas[- ]is\b",
    r"\bbroken\b",
    r"\bfaulty\b",
    r"\bno\s+(?:gpu|card|display|video|output|power)\b",
    r"\bwater\s*block\b",
    r"\bwaterblock\b",
    r"\bback\s*plate\b",
    r"\bbackplate\b",
    r"\bcooler\s+only\b",
    r"\bheat\s*sink\b",
    r"\bshroud\b",
    r"\bfan(?:s)?\s+(?:only|replacement)\b",
    r"\bbracket\b",
    r"\briser\b",
    r"\bpower\s+cable\b",
    r"\badapter\b",
    r"\bsticker\b",
    r"\breplica\b",
    r"\bdummy\b",
    r"\b3d\s*print",
    # The eBay water-cooling dialect. Block sellers rarely say "water block" --
    # observed live: "EKWB Quantum Vector RTX 3080/3090 Referenc D-RGB Nickel
    # Plexi Active" contains no junk word above. The brands are anchored to the
    # title start because sellers lead with the product's maker: the same brand
    # mid-title is a card with a block fitted ("RTX 3090 Ti FE - Water blocked
    # EK-Quantum Vector"), which is a card.
    r"^\s*(?:ekwb|ek[- ]?quantum|bitspower|alphacool|bykski|barrow\b"
    r"|heatkiller|aqua\s*computer|watercool\b|phanteks\s+glacier"
    r"|corsair\s+(?:hydro|xg7))",
    r"\bgpu\s+block\b",
    r"\bvga\s+block\b",
    r"\bplexi\b",  # block materials -- no card listing says plexi or acetal
    r"\bacetal\b",
    # A title that *starts* with "For" or "fits" is about the named GPU, not
    # selling it: "For MSI RTX3080/ RTX3090 SUPRIM X Fan Heatsink". Anchored to
    # the start because mid-title "for" is sale phrasing ("priced for quick
    # sale"), and "for sale" itself is excluded outright.
    r"^\s*(?:\d+\s*[x×]\s*)?(?:for|fits)\b(?!\s+sale\b)",
    # NVLink bridges name every card they connect and sit at ~$200 -- squarely
    # inside the suspicious-price band for a 3090. But NVLink *capability* is a
    # selling point on real cards, and "with NVLink bridge included" is a card
    # plus a bridge, so mentions preceded by inclusion words don't count.
    r"(?<!with )(?<!includes )(?<!incl )(?<!and )(?<!\+ )(?<!w/ )"
    r"\b(?:nvlink|sli)\s+bridge\b",
    r"\breplacement\s+fans?\b",
    # Datacenter form factors and the parts that mount them. An SXM4 A100 is
    # not a cheap PCIe A100 -- it is a mezzanine module that cannot physically
    # go in a tower, and it prices like one, so matching it to the PCIe catalog
    # entry reads as a bargain that you could never install. The backplane and
    # baseboard are the carriers, not the cards.
    r"\bsxm[2345]?\b",
    r"\bback\s*plane\b",
    r"\bbaseboard\b",
    r"\bmezzanine\b",
    r"\bocp\s+3\.0\b",
)
JUNK_RE = re.compile("|".join(JUNK_PATTERNS), re.IGNORECASE)

# Signals that a used card came out of a mining rig. None is conclusive alone,
# so these score rather than exclude -- a repasted ex-mining 3090 at $450 can
# still be the right buy, you just want to be told.
MINING_PATTERNS = (
    (r"\bmining\b", 3),
    (r"\bmined\b", 3),
    (r"\bhash\s*rate\b", 3),
    (r"\brig\b", 2),
    (r"\bfarm\b", 2),
    (r"\bethereum\b|\beth\b", 2),
    (r"\bunder\s*volt", 1),
    (r"\brepaste[d]?\b", 1),
    (r"\bnew\s+thermal\s+pads?\b", 1),
    (r"\bquantity\s*[:=]?\s*(?:[3-9]|\d{2,})\b", 2),
    (r"\b(?:[3-9]|\d{2,})\s*(?:x|available|in\s+stock|units?)\b", 2),
    (r"\btested\s+working\b", 1),
)
MINING_RES = tuple((re.compile(p, re.IGNORECASE), w) for p, w in MINING_PATTERNS)

CONDITION_PATTERNS = (
    ("refurbished", r"\brefurb(?:ished)?\b|\brenewed\b|\bcertified\s+pre"),
    ("open_box", r"\bopen[- ]box\b|\bopened\b"),
    ("used", r"\bused\b|\bpre[- ]?owned\b|\bsecond\s*hand\b"),
    ("new", r"\bbrand\s+new\b|\bnew\s+sealed\b|\bsealed\b|\bnib\b|\bbnib\b"),
)
CONDITION_RES = tuple((name, re.compile(p, re.IGNORECASE)) for name, p in CONDITION_PATTERNS)

# "$1,599.99" / "$749" / "1599.99 USD". Deliberately does not match bare numbers
# -- "RTX 3090 24GB" would otherwise parse as a $24 card.
PRICE_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)|([0-9][0-9,]*(?:\.[0-9]{2})?)\s?(?:USD|usd)\b")

# Memory capacity, for disambiguating configurable products like Mac Studio.
CAPACITY_RE = re.compile(r"\b(\d{2,4})\s?(?:gb|g)\b", re.IGNORECASE)

# Apple writes core counts the way everyone else writes capacity. "Mac Studio
# M3 Ultra 512GB Unified Memory 32C 80G 16TB SSD" is a 32-core CPU and an
# 80-core GPU, not 80GB of anything -- four listings in one live run read that
# way. Nothing collides today, since the M3 Ultra ships 60 or 80 GPU cores and
# no catalog capacity is either, but the reading is wrong and a config that did
# collide would quietly veto a correct match.
CORE_COUNT_RE = re.compile(r"\b\d{1,3}\s?c\s+\d{1,3}\s?g\b", re.IGNORECASE)

# The same, but only capacities that could be the *card's*. A prebuilt lists its
# system memory beside the GPU ("RTX 5090, 64GB RAM, 2TB SSD"), and reading that
# as VRAM makes every prebuilt contradict its own graphics card. The negative
# lookahead drops anything trailed by a system-memory or storage word. Note
# "GDDR6" survives it: there is no word boundary before the "ddr" in "gddr", so
# a card's own VRAM type is never mistaken for system RAM.
CARD_CAPACITY_RE = re.compile(
    r"\b(\d{2,4})\s?(?:gb|g)\b(?!\s*(?:\b(?:ram|ddr\d|lpddr\d|ssd|nvme|hdd|"
    r"storage|memory\s+ram)\b))",
    re.IGNORECASE,
)

# Multi-card listings. These matter more than they look: "Lot of 6 RTX 3090 -
# $3600" is six cards at $600 each, which is an excellent deal, but read as a
# single card at $3600 it looks like a terrible one and gets discarded. Anchored
# on explicit lot language so "3090 Ti" and "24GB" can't be read as quantities.
LOT_PATTERNS = (
    r"\blot\s+of\s+(\d{1,2})\b",
    r"\bqty\.?\s*[:=]?\s*(\d{1,2})\b",
    r"\bquantity\s*[:=]?\s*(\d{1,2})\b",
    # "3x RTX 3090" is three cards; "Ventus 3X OC" is one card with a
    # triple-fan cooler in its model name. Vendors encode fan count exactly
    # this way -- MSI Ventus 2X/3X, Gigabyte WINDFORCE 3X, Zotac Trinity 3X --
    # and the unguarded pattern turned an observed $4,499.99 5090 into three
    # cards at $1,500. That price then *logs*, because $1,500 against a $2,000
    # reference is nowhere near the bait threshold. A wrong alert is transient;
    # a wrong observation is permanent, so the multiplier now has to be
    # followed by something that could name a card.
    r"\b(\d{1,2})\s*[x×]\s+(?=(?:rtx|gtx|geforce|radeon|nvidia|amd|quadro|tesla"
    r"|msi|asus|evga|gigabyte|zotac|pny|sapphire|xfx|powercolor|inno3d|palit"
    r"|gainward|colorful|founders|dell|hp|lenovo|a\d{3}|h\d{3}|l\d{2})\b)",
    r"\((\d{1,2})\)\s*(?=[a-z])",
    r"\b(\d{1,2})\s*[- ]?pack\b",
    r"\bset\s+of\s+(\d{1,2})\b",
)
LOT_RES = tuple(re.compile(p, re.IGNORECASE) for p in LOT_PATTERNS)

# Whole computers that merely *contain* the card we matched on. Observed live
# on Slickdeals: "ASUS ROG Strix GA35 Gaming Desktop PC, RTX 3090, AMD 9 5900X,
# 32GB DDR4, 1TB SSD - $1,899". That matches the 3090 aliases perfectly, and
# recording $1,899 as a 3090 observation would drag the part's whole price
# distribution upward. These stay visible -- a cheap prebuilt you part out is a
# legitimate way to buy a GPU -- but they never reach the history log.
SYSTEM_PATTERNS = (
    r"\bdesktop\b",
    r"\bgaming\s+pc\b",
    r"\bprebuilt\b",
    r"\bpre[- ]built\b",
    r"\blaptop\b",
    r"\bnotebook\b",
    r"\ball[- ]in[- ]one\b",
    r"\btower\b",
    r"\bbarebone\b",
    # "workstation" stays anchored to "workstation PC": the bare word is in an
    # actual product name (RTX PRO 6000 Blackwell Workstation Edition), so
    # matching it alone would reject the card this project is hunting.
    r"\bwork\s*station\s+pc\b",
    # ...but "AI workstation" is never a card. It is how every builder on eBay
    # advertises a tower, and the "PC" anchor above let all of them through:
    # "ULTRA 9 285K AI Workstation ASUS ROG Astral RTX 5090 128GB DDR5 4TB SSD"
    # was logged as a bare 5090, eleven such rows in a 1,041-row log. They were
    # purged on 2026-08-13 only because they happened to be variation listings
    # too; the same title on an ordinary listing still scored as a card.
    # Checked separately in is_system_listing, against CARD_WORD_RE.
    r"\bsystem\b",
    # How enterprise gear is sold. Found by auditing the price log on
    # 2026-08-08: a "DGX Station RTX-6000 ADA" at $12,550 and an "A6000 +
    # Quadro Sync II Media Server / Render Node" at $10,000 had both been
    # recorded as bare-card prices, because the filter knew "gaming pc" and
    # "desktop" but nothing about how a render farm advertises itself.
    r"\bdgx\s+station\b",
    r"\brender\s+node\b",
    r"\bmedia\s+server\b",
    r"\bgpu\s+server\b",
    r"\bcompute\s+node\b",
    r"\brack\s*mount\b",
    r"\b\d+u\s+server\b",
)
SYSTEM_RE = re.compile("|".join(SYSTEM_PATTERNS), re.IGNORECASE)
AI_WORKSTATION_RE = re.compile(r"\bai\s+work\s*station\b", re.IGNORECASE)
# ...unless the listing calls itself a card. Sellers of bare cards borrow the
# builders' phrase too: "NVIDIA RTX 6000 ADA-Lovelace 48GB Professional Graphics
# GPU Card AI Workstation" ($7,994) and "NVIDIA RTX PRO 6000 Blackwell 96GB
# GDDR7 ECC AI Workstation GPU NEW" ($17,000) both reached the 2026-09-21 digest
# as whole machines undercutting the loose card -- and were never logged. A
# rig quoting RAM or storage stays a rig whatever it calls its GPU.
#
# A card can also say so by its memory. "NVIDIA RTX PRO 6000 Blackwell 96GB
# GDDR7 ECC AI Workstation" ($3,999, eBay 188939006524, seen 2026-09-17) was the
# third bare card wearing the phrase and the one the card word above does not
# reach: it never writes GPU, card or graphics, so nothing contradicted the
# phrase. It led the digest as a whole machine and was never logged -- the
# cheapest RTX PRO 6000 asking price of that week left no row at all. GDDR and
# HBM are memory only a card carries; a machine quotes DDR5 and an SSD, which
# STORAGE_RE reads first.
CARD_WORD_RE = re.compile(
    r"\b(?:graphics|video|gpu)\s+card\b|\bgraphics\s+gpu\b|\bwork\s*station\s+gpu\b"
    r"|\b(?:gddr|hbm)\d",
    re.IGNORECASE,
)

# A CPU model plus memory or storage means the listing is a whole computer even
# when it never says so. Observed live: "HP Omen 45L NVIDIA GeForce RTX 5090,
# 64GB RAM, 2TB SSD, $4987" contains none of the words above, and read as a bare
# card it looks like a catastrophically overpriced 5090 instead of a mid-priced
# prebuilt. Requiring *both* signals keeps "RTX 3090 24GB GDDR6X" from tripping.
CPU_RE = re.compile(
    # The optional [kfst] suffix matters: retail desktop Intel SKUs are nearly
    # always K/KF/KS/F/T variants ("i9-14900KF"), and requiring a boundary
    # straight after the digits made every one of them invisible -- an Omen
    # prebuilt without the word "desktop" then scored as a bare card at
    # prebuilt price.
    # "core ultra 9" is how Intel writes it and "ULTRA 9 285K" is how eBay
    # sellers do, so the "core" cannot be required. The SKU digits carry the
    # match instead, which keeps the bare marketing word from firing on a
    # "Ventus 3X OC Ultra" cooler.
    r"\b(?:i[3579][- ]?\d{4,5}(?:[kfst]{1,2})?|(?:core\s+)?ultra\s+\d\s+\d{3}[a-z]{0,2}"
    r"|ryzen\s+\d|epyc|threadripper|\d{4}x3d|\d{4,5}h[xks]\b|xeon)\b",
    re.IGNORECASE,
)
# "512GB ECC RAM" is a workstation stating its memory, and the unguarded
# pattern missed it because ECC sits between the capacity and the word RAM --
# which is how a $25,400 Threadripper Pro box reached the matcher as a card.
STORAGE_RE = re.compile(
    r"\b\d+\s?(?:gb|tb)\s+(?:ecc\s+)?(?:ssd|nvme|ram|ddr[45])\b", re.IGNORECASE
)
# Words that describe a machine rather than a card. Never load-bearing alone --
# "Workstation" is in the RTX PRO 6000 Blackwell Workstation Edition's own name
# -- so these only count next to a CPU model. See is_system_listing.
BUILD_WORD_RE = re.compile(
    r"\bwork\s*station\b|\bserver\b|\bnode\b|\bbuild\b|\brig\b", re.IGNORECASE
)

# Laptops. These matter more than prebuilts because a mobile RTX 5090 is not a
# cut-down desktop 5090, it is a different chip with 24GB instead of 32GB and
# roughly half the power budget. Matching one to the desktop catalog entry would
# be wrong rather than merely imprecise, so these are rejected outright.
# Observed live: 'Acer Predator Helios AI (Cert. Refurb): 16" QHD+ 240Hz OLED,
# Intel Ultra 9 275HX, RTX 5090' -- no occurrence of the word "laptop".
MOBILE_PATTERNS = (
    r"\blaptop\b",
    r"\bnotebook\b",
    r"\bmobile\s+(?:gpu|graphics)\b",
    r"\d{2}(?:\.\d)?\s*[\"”″]",  # screen size: 16" / 18" / 18″
    r"\b\d{2}(?:\.\d)?[- ]inch\b",
    r"\b\d{2,3}\s?hz\b",  # refresh rate
    r"\b(?:qhd|uhd|fhd|wqxga)\+?\b",
    r"\bmini[- ]led\b",
    r"\b\d{4,5}h[xks]\b",  # mobile CPU suffix: 275HX, 14900HX, 9800HS
    # Laptop *families*, for the listings whose model name carries none of the
    # signals above. Observed 2026-08-17: "nvidia rtx pro 5000 blackwell for
    # dell pro max 18 plus" -- a mobile module for a Dell laptop -- was logged
    # at $3,000 against the 48GB desktop card's $4,500 reference, and was the
    # cheapest observation in that bucket. The "18" is a screen size, but it is
    # written without an inch mark, so no pattern above sees it.
    r"\bdell\s+pro\s+max\b",
    r"\bthinkpad\b",
    r"\bprecision\s+\d{4}\b",
    r"\bzbook\b",
    r"\belitebook\b",
    r"\bprobook\b",
    # "9i" too: "Legion 9i Gen 10 Intel (18″) with RTX 5090" was logged as a
    # new desktop 5090 at $4,800 on 2026-09-20.
    r"\blegion\s+(?:pro\s+)?\di?\b",
    r"\bmacbook\b",
    r"\bblade\s+1[45678]\b",  # Razer Blade
    r"\brog\s+(?:zephyrus|strix\s+scar|flow)\b",
    r"\bpredator\s+helios\b",
    r"\bnitro\s+\d\b",
    r"\bomen\s+1[4-8]\b",
    r"\bvivobook\b|\bzenbook\b",
)
MOBILE_RE = re.compile("|".join(MOBILE_PATTERNS), re.IGNORECASE)

# Parts whose listings routinely name a GPU for compatibility reasons. Observed
# live: "Seasonic Focus GX 850W ATX 3.1 PSU | Fully Modular | PCIe 5.1 | RTX
# 5080 & ..." matched as a $100 RTX 5080.
ACCESSORY_PATTERNS = (
    r"\bpsu\b",
    r"\bpower\s+supply\b",
    r"\b\d{3,4}\s?w\s+(?:atx|psu|power)\b",
    r"\bmotherboard\b",
    r"\bmonitor\b",
    r"\bcase\b(?!\s*(?:study|fan))",
    r"\bcpu\s+cooler\b",
    r"\baio\s+cooler\b",
)
ACCESSORY_RE = re.compile("|".join(ACCESSORY_PATTERNS), re.IGNORECASE)

# Card model numbers, catalog or not. find_all_parts can only see cards this
# project would buy, and the listings that need catching name the ones it
# wouldn't: "Dell NVIDIA GeForce RTX 3060 3070 3080 3090 8 10 12 24GB GDDR6X"
# names four cards of which exactly one, the 3090, is in the catalog -- so the
# bundle check saw a single unambiguous part and let the price through. It was
# a 3060 Ti's price.
#
# GeForce numbering always ends in 50/60/70/80/90, which is what keeps the
# pattern off the other four-digit numbers a listing is full of: 1000W
# supplies, DDR5-6000 kits, 3840x2160 panels, model years. The professional
# line is spelled out separately because A4000 and A4500 break that rule.
# The datacenter line is listed out because a menu only needs *one* catalogued
# card to look unambiguous: "A100 40GB / V100 32GB" names two, and
# find_all_parts sees one, because V100 is not a card this project would buy
# and so is not in the catalog to be counted.
#
# Spelled out one SKU at a time rather than as a letter-plus-digits shape. The
# shape version cost six real RTX 3090s on its first live run: MSI stamps a
# part number in the title -- "MSI GeForce RTX 3090 GAMING X TRIO 24GB GDDR6X
# Graphics Card 912-V388-054" -- and V388 read as a second model, which would
# have held the most-logged part in the catalog out of its own distribution.
MODEL_NUMBER_PATTERNS = (
    r"\b[1-5][0-9][5-9]0\b",
    r"\ba[2-6][05]00\b",
    r"\b(?:a100|a800|h100|h200|h800|v100|p100)\b",
    r"\bl40s?\b",
    r"\bmi\d{3}[a-z]?\b",
)
MODEL_NUMBER_RE = re.compile("|".join(MODEL_NUMBER_PATTERNS), re.IGNORECASE)

# "36GB-128GB RAM", "36GB to 128GB RAM", "36-128GB Unified Memory". The memory
# word is required: "Mac mini M4 Pro 64GB-512GB" is one machine's memory and
# storage, not a range. The bare-first form must be tight and ascending, or
# "RTX 5090 - 32GB" reads as a range.
MEMORY_RANGE_RE = re.compile(
    r"\b(\d{1,4})(?:\s?gb\s?(?:-|–|to)\s?|[-–])(\d{2,4})\s?gb\b"
    r"(?=\s*(?:ram|memory|unified)\b)",
    re.IGNORECASE,
)


@dataclass
class MatchResult:
    part: Part | None
    # Price for the whole listing, exactly as advertised.
    price: float | None
    condition: str
    mining_score: int
    junk: bool
    # How many units the listing covers. Everything downstream scores on
    # unit_price, so a lot of six is judged as six cards, not one expensive one.
    quantity: int = 1
    # True when the listing is a whole computer that contains the matched part
    # rather than the part itself. Still worth showing, never worth recording.
    is_system: bool = False
    # True when one post sells several distinct catalog parts, so no single
    # price can be attributed to the matched one. Shown, never recorded.
    is_bundle: bool = False
    # Which alias fired, for debugging a bad match.
    matched_on: str = ""

    @property
    def unit_price(self) -> float | None:
        if self.price is None:
            return None
        return self.price / max(self.quantity, 1)

    @property
    def mining_risk(self) -> str:
        if self.mining_score >= 4:
            return "high"
        if self.mining_score >= 2:
            return "moderate"
        return "low"


# "Max-Q" is spelled three ways by three sellers and it is the only thing
# separating a 300W 2-slot card from a 600W one. Collapsing the variants to a
# single token means aliases and require_all can both name it once.
_MAXQ_RE = re.compile(r"\bmax[- ]?q\b")


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, and neutralise the separators vendors use.

    "RTX-3090" / "RTX_3090" / "RTX  3090" all have to reach the same matcher.
    Hyphens survive elsewhere, but the Max-Q family is folded to one spelling:
    "Max-Q", "Max Q" and "MaxQ" all become "maxq", on both sides of the match.
    """
    text = text.lower()
    text = text.replace("_", " ").replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return _MAXQ_RE.sub("maxq", text)


def extract_price(text: str) -> float | None:
    """First plausible price in a title. Reddit puts it there; eBay does not."""
    for match in PRICE_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        # Titles quote rebates ("$1,799 - $200 off") and shipping ("$12 ship").
        # The first match is the asking price in nearly every case, but reject
        # values too small to be any part we care about.
        if value >= 50:
            return value
    return None


def detect_condition(text: str) -> str:
    lowered = text.lower()
    for name, pattern in CONDITION_RES:
        if pattern.search(lowered):
            return name
    return "unknown"


def mining_score(text: str) -> int:
    lowered = text.lower()
    return sum(weight for pattern, weight in MINING_RES if pattern.search(lowered))


def is_junk(text: str) -> bool:
    return bool(JUNK_RE.search(text))


def is_system_listing(text: str, part: Part | None) -> bool:
    """Is this a whole computer that happens to contain `part`?

    Only meaningful for cards. Unified-memory entries (Mac Studio, Framework
    Desktop, DGX Spark) *are* whole computers, so the same words that condemn a
    GPU listing are the correct description there.
    """
    if part is None or part.kind.value == "unified":
        return False
    if SYSTEM_RE.search(text):
        return True
    if AI_WORKSTATION_RE.search(text) and (
        STORAGE_RE.search(text) or not CARD_WORD_RE.search(text)
    ):
        return True
    # The implicit case: a CPU and memory/storage named alongside the GPU.
    if CPU_RE.search(text) and STORAGE_RE.search(text):
        return True
    # ...or a CPU named alongside a build word, for the machines that quote
    # neither RAM nor storage in the title. "Intel Xeon w7-3565X 2x RTX PRO
    # 6000 Blackwell AI/Machine Learning Workstation" was logged at $21,954 as
    # a bare card: the ai-workstation pattern above wants those two words
    # adjacent and "Machine Learning" sits between them, and with no "64GB RAM"
    # to pair with, the Xeon had nothing to combine with either.
    #
    # The pairing is what makes the bare word safe. "Workstation" alone is part
    # of an actual product name -- RTX PRO 6000 Blackwell Workstation Edition
    # -- so it can never condemn a listing on its own; it takes a Xeon or a
    # Threadripper beside it, and no bare card names one of those.
    return bool(CPU_RE.search(text) and BUILD_WORD_RE.search(text))


def is_mobile_listing(text: str, part: Part | None) -> bool:
    """Is this a laptop? Mobile GPUs are different parts, not cheaper ones."""
    if part is None or part.kind.value == "unified":
        return False
    return bool(MOBILE_RE.search(text))


def is_accessory_listing(text: str, part: Part | None) -> bool:
    """A PSU or motherboard that names a GPU only for compatibility."""
    if part is None or part.kind.value == "unified":
        return False
    return bool(ACCESSORY_RE.search(text))


def detect_quantity(text: str) -> int:
    """How many units one listing covers. 1 when it doesn't say otherwise.

    Capped at 12: past that it's a pallet auction or a typo, and either way the
    per-unit price stops being a thing an individual can act on.
    """
    for pattern in LOT_RES:
        found = pattern.search(text)
        if not found:
            continue
        try:
            count = int(found.group(1))
        except (ValueError, IndexError):
            continue
        if 2 <= count <= 12:
            return count
    return 1


def names_multiple_models(text: str) -> bool:
    """Does one title name more than one distinct card?

    Distinct, so "RTX 3090 / 3090 Ti" is the one card it describes rather than
    two, and a title that repeats its own model number stays a single product.
    """
    return len({found.group(0).lower() for found in MODEL_NUMBER_RE.finditer(text)}) > 1


def names_memory_range(text: str) -> bool:
    return any(int(low) < int(high) for low, high in MEMORY_RANGE_RE.findall(text))


def _candidate_terms(part: Part) -> list[str]:
    """Every string that should identify this part, longest first.

    Longest-first is what stops "RTX 3090 Ti" being claimed by the 3090 entry:
    both match, but the more specific alias is tried first and wins.
    """
    terms = {part.name.lower(), *(alias.lower() for alias in part.aliases)}
    return sorted((_normalize(t) for t in terms), key=len, reverse=True)


# Built once: (normalized alias, part), longest alias first across all parts.
_ALIAS_INDEX: list[tuple[str, Part]] = sorted(
    ((term, part) for part in PARTS for term in _candidate_terms(part)),
    key=lambda pair: len(pair[0]),
    reverse=True,
)


# r/hardwareswap encodes direction in the title: [H]ave is what the poster is
# selling, [W]ant is what they want back. The two halves must never be confused
# -- "[USA-MI][H] Local cash, PayPal [W] RTX 5090" is someone *buying* a 5090,
# and its body ("preferably below $3800") would otherwise parse into a listing
# at $3800. Sampling the subreddit while building this, three of seven GPU posts
# were purchase requests, so this is the common case rather than an edge case.
HAVE_WANT_RE = re.compile(r"\[\s*h\s*\](.*?)(?:\[\s*w\s*\]|$)", re.IGNORECASE | re.DOTALL)


def split_have_want(title: str) -> tuple[str, bool]:
    """Return (text to match against, whether this was a have/want title).

    For a have/want title, only the [H] section describes goods for sale, so
    that is all the part matcher should ever see. Titles without the convention
    pass through untouched.
    """
    found = HAVE_WANT_RE.search(title)
    if not found:
        return title, False
    return found.group(1).strip(), True


def _present(term: str, haystack: str) -> bool:
    """Word-boundary anchored containment.

    Boundaries matter: "a100" must not match inside "a1000", and "3090" must
    not match inside "13090".
    """
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack))


def _excluded(haystack: str, part: Part) -> bool:
    """Does the title name something that rules this part out?

    Checked everywhere a part can be claimed, so an exclusion holds for
    find_part and find_all_parts alike -- otherwise the base part would be
    rejected as the match and still counted as a second card in the bundle
    check, turning a Max-Q listing into a two-GPU bundle.
    """
    return any(
        _present(_normalize(token), haystack) for token in part.excludes
    )


def _alias_hits(haystack: str) -> list[tuple[int, int, str, Part]]:
    """Every alias match in the text, as (start, end, term, part) spans.

    Spans, not just membership, because alias length alone cannot rank
    specificity across parts: "geforce rtx 3090" is longer than "rtx 3090 ti",
    so longest-alias-first hands a "GeForce RTX 3090 Ti" title to the plain
    3090 -- and, since both parts' aliases are present, find_all_parts then
    declares the title a bundle with itself. The text region decides instead:
    where two matches overlap, the one reaching furthest is the most specific
    reading of that region.
    """
    hits: list[tuple[int, int, str, Part]] = []
    for term, part in _ALIAS_INDEX:
        for found in re.finditer(
            rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack
        ):
            hits.append((found.start(), found.end(), term, part))
    # Furthest end wins an overlap; longer span breaks ties. Sorting first
    # means the keep-loop below only ever discards the less specific reading.
    hits.sort(key=lambda hit: (hit[1], hit[1] - hit[0]), reverse=True)
    kept: list[tuple[int, int, str, Part]] = []
    for start, end, term, part in hits:
        if any(start < k_end and k_start < end for k_start, k_end, _, _ in kept):
            continue
        kept.append((start, end, term, part))
    return kept


# Parts matched by token sets rather than contiguous aliases, most specific
# (most tokens) first.
_TOKEN_INDEX: list[Part] = sorted(
    (part for part in PARTS if part.require_all),
    key=lambda part: len(part.require_all),
    reverse=True,
)


def find_all_parts(text: str) -> list[Part]:
    """Every distinct catalog part named in `text`.

    Used to spot bundles. A private-sale post reading "[H] Gigabyte 4090, 3090
    FE, 32in monitor, 32gb DDR5" is four items under one headline with prices
    scattered through the body, and picking any single price out of that and
    attaching it to the 4090 would be a guess. Bundles stay visible -- they are
    often where the good deals are -- but never reach the price log.
    """
    haystack = _normalize(text)
    found: dict[str, Part] = {}

    for part in _TOKEN_INDEX:
        if _excluded(haystack, part):
            continue
        tokens = tuple(_normalize(t) for t in part.require_all)
        if all(_present(token, haystack) for token in tokens) and _capacity_agrees(
            haystack, part
        ):
            found.setdefault(part.key, part)

    for _, _, _, part in _alias_hits(haystack):
        if part.key in found:
            continue
        if _excluded(haystack, part):
            continue
        if not _capacity_agrees(haystack, part):
            continue
        found.setdefault(part.key, part)

    return list(found.values())


def find_part(text: str) -> tuple[Part | None, str]:
    """Best catalog match for a listing title, plus the term that matched."""
    haystack = _normalize(text)

    # Token matching first: it is strictly more specific than a single alias,
    # since every required token has to be present.
    for part in _TOKEN_INDEX:
        if _excluded(haystack, part):
            continue
        tokens = tuple(_normalize(t) for t in part.require_all)
        if not all(_present(token, haystack) for token in tokens):
            continue
        if not _capacity_agrees(haystack, part):
            continue
        return part, " + ".join(tokens)

    for _, _, term, part in _alias_hits(haystack):
        if _excluded(haystack, part):
            continue
        # Capacity is checked for every kind now, not just unified: a stated
        # capacity that contradicts the part means a different card, and the
        # log audit found a 72GB PRO 5000 Blackwell recorded against the 48GB
        # entry. _capacity_agrees knows the difference between "unstated"
        # (fine for a discrete card) and "contradicted" (never fine).
        if not _capacity_agrees(haystack, part):
            continue
        return part, term

    return None, ""


def _capacity_agrees(haystack: str, part: Part) -> bool:
    """For configurable products, does a stated capacity match this SKU?

    Unified-memory boxes are sold as one model across a 5x memory range, and
    memory is the entire point of buying one. A Mac Studio M3 Ultra at $3,600 is
    an ordinary price for the 96GB and an extraordinary one for the 512GB, so
    guessing wrong is expensive in the direction that matters. An unstated
    capacity therefore means *no match*, not a hopeful one -- which is why
    "Apple Mac Studio MU963LL/A (Early 2025) Desktop Computer $1699" is
    correctly skipped rather than assigned to whichever SKU happens to be first.
    """
    haystack = CORE_COUNT_RE.sub(" ", haystack)
    stated = {int(m.group(1)) for m in CAPACITY_RE.finditer(haystack)}
    if part.kind.value == "unified":
        # Memory *is* the product here, so silence means no match rather than a
        # hopeful one -- a Mac Studio M3 Ultra spans $4,099 to $26,000 across
        # capacities under one name.
        return part.vram_gb in stated if stated else False

    # Discrete cards are terser: "RTX A6000 Pro-Level Graphics Card" states no
    # capacity and is still an A6000, so silence is fine. A *contradiction* is
    # not. Found in the log audit on 2026-08-08: "NVIDIA RTX PRO 5000 72GB
    # Blackwell" was recorded against the 48GB entry at $11,857, and the 72GB
    # is a different card the catalog doesn't carry. Only capacities in the
    # plausible VRAM range count, so "64GB RAM" or "2TB SSD" beside a GPU
    # cannot veto it.
    card = {
        int(m.group(1))
        for m in CARD_CAPACITY_RE.finditer(haystack)
        if 8 <= int(m.group(1)) <= 200
    }
    if not card:
        return True
    return part.vram_gb in card


def match(
    title: str,
    *,
    body: str = "",
    price: float | None = None,
    multi_variant: bool = False,
) -> MatchResult:
    """Parse one listing.

    `price` comes from the source when it has a structured field (eBay), and is
    scraped from the title when it doesn't (Reddit, Slickdeals). `body` is
    searched for condition and mining signals but never for the part itself --
    a comment mentioning "I also have a 3090" must not retag the listing.

    `multi_variant` is the source saying this row is one option out of several
    priced behind a single listing, so the title belongs to the group and the
    price belongs to an option the title never identifies.
    """
    # Nothing to check. A title is the only evidence that a listing is what its
    # part key claims -- every filter in this module reads it -- so an empty one
    # cannot be matched, only guessed at. 571 of the 1,417 rows in the log
    # carry no title (a storage bug fixed on 2026-08-13, but the rows remain)
    # and they cannot be audited for mismatch even in hindsight. Refusing them
    # keeps that from recurring.
    if not title.strip():
        return MatchResult(None, None, "unknown", 0, junk=True)

    if is_junk(title):
        return MatchResult(None, None, "unknown", 0, junk=True)

    # On have/want boards, match only against what's actually for sale.
    sale_text, is_swap = split_have_want(title)
    part, matched_on = find_part(sale_text)

    # A laptop 5090 and a desktop 5090 share a marketing name and nothing else.
    # A PSU that lists GPU compatibility is not a GPU. Neither is a near miss
    # worth surfacing, so both drop the part entirely rather than flagging it.
    if is_mobile_listing(title, part) or is_accessory_listing(title, part):
        return MatchResult(None, None, "unknown", 0, junk=True, matched_on=matched_on)

    # A bundle and a menu look identical in a title and are opposites in fact.
    # "RTX 3090 + 4090, $2500" sells you both cards for that money and is worth
    # seeing; "RTX 3060 3070 3080 3090, $593" sells you one of four and quotes
    # whichever option the search surfaced, which was the 3060 Ti. Only the
    # source can tell them apart, so the drop needs both signals: several
    # models named, and the source reporting several prices behind them.
    #
    # Dropped outright rather than downgraded, on the same grounds as a mobile
    # or accessory match -- the card named is not the card on offer, and a
    # wrong identity is worse than no match at all.
    #
    # A prebuilt is the same menu with one name on it: the title names the
    # flagship build and the dropdown is the graphics card. Observed
    # 2026-09-17, "AMD RYZEN 9 9950X3D2 Gaming PC NVIDIA RTX 5090" quoted
    # $1,999.99 for its no-GPU option, beside a 5090 option that was out of
    # stock, and read as a 5090 machine undercutting every loose 5090.
    #
    # So is a memory range: on a unified-memory machine the capacity is the
    # part. Observed 2026-09-24, "MacBook Pro M3 Max 16.2-inch 36GB-128GB RAM"
    # quoted $2,199 for its 36GB option, with every larger size out of stock,
    # and read as an M3 Max 128GB at 39% under reference.
    several_models = names_multiple_models(sale_text)
    if multi_variant and (
        several_models or is_system_listing(title, part) or names_memory_range(sale_text)
    ):
        return MatchResult(None, None, "unknown", 0, junk=True, matched_on=matched_on)

    resolved_price = price if price is not None else extract_price(title)
    # Private-sale boards put the price in the post, not the headline
    # ("$1000 local @ 38506"). Only consulted as a fallback, and only for
    # have/want posts -- on a retail feed a body price is as likely to be a
    # competitor's price or a historical low as it is the asking price.
    #
    # Requires a matched part. Without one there is nothing for the price to be
    # the price *of*, and a want-to-buy post's body ("willing to pay up to
    # $1200") would otherwise leave a plausible-looking number attached to a
    # result that means the opposite of a sale.
    if resolved_price is None and is_swap and part is not None:
        resolved_price = extract_price(body)

    context = f"{title}\n{body}"

    is_system = is_system_listing(title, part)
    # A whole computer matched on a bare model number is almost certainly using
    # that number as its own. Observed live: "USED Dell G5 5090 Tower Gaming
    # Desktop, Intel Core i7" -- the G5 5090 is a 2019 Dell desktop SKU
    # containing no RTX 5090 at all. Real prebuilts put a GPU marker right
    # before the number ("HP Omen 45L RTX 5090"), so a system listing keeps a
    # digits-only match only when the title does too. The check is adjacency in
    # the title, not the alias's own shape, because the catalog aliases for
    # these parts are the bare numbers. Non-system listings are exempt:
    # hardwareswap brevity ("5090, local only") is the normal register there.
    if is_system and matched_on.strip().isdigit():
        marker = re.search(
            rf"(?:rtx|gtx|geforce|nvidia|quadro)\s*{matched_on.strip()}",
            _normalize(sale_text),
        )
        if not marker:
            part, matched_on, is_system = None, "", False

    return MatchResult(
        part=part,
        price=resolved_price,
        condition=detect_condition(context),
        mining_score=mining_score(context),
        junk=False,
        # Quantity comes from the title only. A body saying "I have 3 more" is
        # a follow-on offer, not a discount on the thing being advertised.
        quantity=detect_quantity(title),
        is_system=is_system,
        # Catalog parts *or* bare model numbers: one price against several
        # named cards can't be attributed to any of them either way.
        is_bundle=len(find_all_parts(sale_text)) > 1 or several_models,
        matched_on=matched_on,
    )
