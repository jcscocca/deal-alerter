"""What each piece of hardware actually is, in the terms that matter for LLMs.

The Steam version of this project got price history handed to it by ITAD, and a
game is a game -- a $40 game and a $40 game are comparable. Hardware is not:
$800 for 24GB at 936 GB/s and $800 for 128GB at 256 GB/s are wildly different
purchases, and neither the listing nor any API tells you which is which. So the
specs live here.

Three numbers drive every verdict in this project:

  vram_gb      what you can load at all. Below the model size, nothing else
               matters -- you simply cannot run it.
  bandwidth    generation speed. Decoding is memory-bound, so tokens/sec scales
               almost linearly with GB/s and barely at all with FLOPs.
  tdp_w        whether it goes in the machine you own, or the machine you'd
               have to buy to hold it.

`reference_price` is the anchor for "is this cheap?" before the local history
log has enough observations to answer it properly. It is meant to be what the
thing actually *sells* for, not what it is listed at -- the whole verdict
engine reads it as real transaction value.

`reference_basis` records whether that promise is kept. Eleven entries carry a
Terapeak sold average and say so; the rest are estimates, and are held below
the push threshold until somebody verifies them. Correcting one means updating
both fields together: a number sourced from sold data with the basis left at
"estimate" is merely undertrusted, but an estimate labelled "sold" will ring
your phone about a price nobody has ever paid.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(str, Enum):
    """Coarse category, used by watchlist `class` filters."""

    CONSUMER_GPU = "consumer"
    PRO_GPU = "pro"
    DATACENTER = "datacenter"
    UNIFIED = "unified"  # Mac / Strix Halo / GB10 -- CPU and GPU share one pool


@dataclass(frozen=True)
class Part:
    key: str
    name: str
    kind: Kind
    vram_gb: int
    # GB/s. The single best predictor of tokens/sec for a model that fits.
    bandwidth_gb_s: int
    tdp_w: int
    reference_price: float
    year: int
    # Ampere / Ada / Blackwell / Apple / RDNA -- mixing architectures in one box
    # is what stops you tensor-parallelising cleanly, so the engine tracks it.
    arch: str
    # Where `reference_price` came from. "sold" means a real transaction average
    # (Terapeak); "estimate" means somebody typed a plausible number in.
    #
    # This is not bookkeeping. Every verdict on the reference path is a claim
    # about how far under real value a price sits, and that claim is only as
    # good as the anchor. A 2026-08-17 audit found the two populations sit on
    # different scales -- asking prices ran 1.48x a sold-sourced anchor at the
    # median but 1.69x an estimated one, with a low tail 15 points closer to
    # the alert line -- so a single set of thresholds cannot mean the same
    # thing for both. Estimates are held below push until they are verified.
    reference_basis: str = "estimate"
    # PCIe slots physically occupied. None for things that aren't cards.
    slots: float | None = None
    # NVLink lets a matched pair pool VRAM over a fast private link instead of
    # going through PCIe. Dropped after Ampere on consumer cards.
    nvlink: bool = False
    # fp8 (Ada+) and fp4 (Blackwell) roughly halve/quarter memory per weight
    # with hardware support, which is worth real money at a given capacity.
    low_precision: str = "fp16"
    # Fraction of nominal memory actually usable for weights + KV cache. Macs
    # reserve a chunk for the OS; discrete cards lose a little to the driver.
    usable_fraction: float = 0.94
    aliases: tuple[str, ...] = ()
    # Tokens that must *all* appear somewhere in the title, in any order and not
    # necessarily adjacent. Aliases require a contiguous substring, which real
    # listings rarely provide: "Apple Mac Studio MU973LL/A (Early 2025) M3 Ultra
    # 28-Core CPU; 96GB" contains neither "mac studio m3 ultra 96gb" nor "m3
    # ultra 96", but does contain "mac studio" and "m3 ultra" separately.
    require_all: tuple[str, ...] = ()
    # Tokens whose presence rules this part *out*, checked before anything else
    # can claim the listing. A variant that carries its parent's whole name
    # needs this and aliases cannot express it: every Max-Q title contains
    # "RTX PRO 6000" too, so without an exclusion the base entry wins on a
    # title that names the variant, and both entries match at once -- which
    # find_all_parts then reads as a two-card bundle.
    excludes: tuple[str, ...] = ()
    note: str = ""

    @property
    def usable_vram_gb(self) -> float:
        return self.vram_gb * self.usable_fraction

    @property
    def dollars_per_gb(self) -> float:
        return self.reference_price / self.vram_gb

    @property
    def capacity_bandwidth(self) -> float:
        """Capacity times speed: GB of VRAM x TB/s of bandwidth.

        The denominator of the combined index. Scaled to TB/s rather than GB/s
        purely so the resulting dollar figure is readable -- a 3090 comes out
        near $45 per GB-TB/s instead of $0.045.
        """
        return self.vram_gb * self.bandwidth_gb_s / 1000

    @property
    def dollars_per_gb_bandwidth(self) -> float:
        return self.reference_price / self.capacity_bandwidth


# Ordered roughly by how interesting each is for local inference, not by price.
PARTS: tuple[Part, ...] = (
    # ------------------------------------------------------------ pro / Blackwell
    Part(
        key="rtx_pro_6000_blackwell_maxq",
        name="RTX PRO 6000 Blackwell Max-Q",
        kind=Kind.PRO_GPU,
        vram_gb=96,
        bandwidth_gb_s=1792,
        tdp_w=300,
        reference_price=9042.0,  # Terapeak sold avg, new, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Blackwell",
        slots=2.0,
        low_precision="fp4",
        aliases=("rtx pro 6000 maxq", "pro 6000 maxq"),
        # Tokens, not an alias: real titles put the capacity and memory type
        # between the model and the variant -- "RTX PRO 6000 Blackwell 96GB
        # GDDR7 Max-Q Edition" contains no contiguous "rtx pro 6000 max-q" --
        # so every Max-Q card was landing in the Workstation bucket instead.
        require_all=("rtx pro 6000", "maxq"),
        note="300W and 2-slot: the only 96GB card that drops into a normal tower.",
    ),
    Part(
        key="rtx_pro_6000_blackwell",
        name="RTX PRO 6000 Blackwell Workstation",
        kind=Kind.PRO_GPU,
        vram_gb=96,
        bandwidth_gb_s=1792,
        tdp_w=600,
        reference_price=9268.0,  # Terapeak sold avg, new, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Blackwell",
        slots=2.0,
        low_precision="fp4",
        aliases=("rtx pro 6000", "pro 6000 blackwell", "rtxpro6000"),
        # The 600W Workstation card and the 300W Max-Q share every word of
        # their name except this one. Different TDP, different chassis, and the
        # log had Max-Q cards recorded against this entry until 2026-08-17.
        excludes=("maxq",),
    ),
    Part(
        key="rtx_pro_5000_blackwell",
        name="RTX PRO 5000 Blackwell 48GB",
        kind=Kind.PRO_GPU,
        vram_gb=48,
        bandwidth_gb_s=1344,
        tdp_w=300,
        reference_price=4500.0,
        year=2025,
        arch="Blackwell",
        slots=2.0,
        low_precision="fp4",
        aliases=("rtx pro 5000",),
    ),
    Part(
        key="rtx_6000_ada",
        name="RTX 6000 Ada 48GB",
        kind=Kind.PRO_GPU,
        vram_gb=48,
        bandwidth_gb_s=960,
        tdp_w=300,
        reference_price=4200.0,
        year=2022,
        arch="Ada",
        slots=2.0,
        low_precision="fp8",
        aliases=("rtx 6000 ada generation", "rtx6000ada", "6000 ada"),
        note="No NVLink. Two of these talk over PCIe only.",
    ),
    Part(
        key="rtx_a6000",
        name="RTX A6000 48GB",
        kind=Kind.PRO_GPU,
        vram_gb=48,
        bandwidth_gb_s=768,
        tdp_w=300,
        reference_price=2754.0,  # Terapeak sold avg, used, 2026-08-08
        reference_basis="sold",
        year=2020,
        arch="Ampere",
        slots=2.0,
        nvlink=True,
        aliases=("a6000", "rtx a6000 48gb"),
        note="Last 48GB card with NVLink. A matched pair pools to 96GB.",
    ),
    Part(
        key="l40s",
        name="NVIDIA L40S 48GB",
        kind=Kind.DATACENTER,
        vram_gb=48,
        bandwidth_gb_s=864,
        tdp_w=350,
        reference_price=6500.0,
        year=2023,
        arch="Ada",
        slots=2.0,
        low_precision="fp8",
        aliases=("l40 s", "l40-s"),
        note="Passive cooling -- needs real chassis airflow, not a desktop case.",
    ),
    # ---------------------------------------------------------------- consumer
    Part(
        key="rtx_5090",
        name="RTX 5090 32GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=32,
        bandwidth_gb_s=1792,
        tdp_w=575,
        reference_price=3142.0,  # Terapeak sold avg, new, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Blackwell",
        slots=3.0,
        low_precision="fp4",
        aliases=("5090", "geforce rtx 5090"),
        note="Fastest memory you can buy without going pro. 575W and transient "
        "spikes past 600W -- the 1000 GT handles one, not two.",
    ),
    Part(
        key="rtx_4090",
        name="RTX 4090 24GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=24,
        bandwidth_gb_s=1008,
        tdp_w=450,
        reference_price=1289.0,  # Terapeak sold avg, used, 2026-08-08
        reference_basis="sold",
        year=2022,
        arch="Ada",
        slots=3.0,
        low_precision="fp8",
        aliases=("4090", "geforce rtx 4090"),
        note="Discontinued; used prices held up unusually well.",
    ),
    Part(
        key="rtx_3090",
        name="RTX 3090 24GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=24,
        bandwidth_gb_s=936,
        tdp_w=350,
        reference_price=1000.0,  # Terapeak sold avg, used, 2026-08-08
        reference_basis="sold",
        year=2020,
        arch="Ampere",
        slots=2.5,
        nvlink=True,
        aliases=("3090", "geforce rtx 3090"),
        note="The value play. NVLink pairs, and 936 GB/s still beats every "
        "unified-memory box on the market.",
    ),
    Part(
        key="rtx_3090_ti",
        name="RTX 3090 Ti 24GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=24,
        bandwidth_gb_s=1008,
        tdp_w=450,
        reference_price=1010.0,  # Terapeak sold avg, used, 2026-08-08
        reference_basis="sold",
        year=2022,
        arch="Ampere",
        slots=3.0,
        nvlink=False,
        aliases=("3090 ti", "3090ti"),
        note="Faster than a 3090 but lost NVLink. Rarely worth the premium.",
    ),
    Part(
        key="rtx_5080",
        name="RTX 5080 16GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=16,
        bandwidth_gb_s=960,
        tdp_w=360,
        reference_price=1000.0,
        year=2025,
        arch="Blackwell",
        slots=2.0,
        low_precision="fp4",
        aliases=("5080",),
    ),
    # ------------------------------------------------------------- AMD / Intel
    # Everything above this line is NVIDIA, which is not a statement about the
    # hardware so much as about the software. These four carry real capacity at
    # real bandwidth for a fraction of the CUDA tax, and llama.cpp runs on all
    # of them; vLLM, bitsandbytes and most quantisation tooling do not, or do
    # only on a lagging fork. Priced accordingly, and worth watching for it.
    Part(
        key="radeon_pro_w7900",
        name="Radeon PRO W7900 48GB",
        kind=Kind.PRO_GPU,
        vram_gb=48,
        bandwidth_gb_s=864,
        tdp_w=295,
        reference_price=2600.0,
        year=2023,
        arch="RDNA3",
        slots=3.0,
        aliases=("w7900", "radeon pro w7900"),
        note="48GB at A6000 bandwidth for less money. ROCm only -- no NVLink, "
        "no vLLM fast path, and 3 slots against the A6000's 2.",
    ),
    Part(
        key="radeon_pro_w7800",
        name="Radeon PRO W7800 32GB",
        kind=Kind.PRO_GPU,
        vram_gb=32,
        bandwidth_gb_s=576,
        tdp_w=260,
        reference_price=1800.0,
        year=2023,
        arch="RDNA3",
        slots=2.0,
        aliases=("w7800", "radeon pro w7800"),
    ),
    Part(
        key="radeon_ai_pro_r9700",
        name="Radeon AI PRO R9700 32GB",
        kind=Kind.PRO_GPU,
        vram_gb=32,
        bandwidth_gb_s=640,
        tdp_w=300,
        reference_price=1300.0,
        year=2025,
        arch="RDNA4",
        slots=2.0,
        low_precision="fp8",
        aliases=("r9700", "radeon ai pro r9700"),
        note="RDNA4 brings fp8, which is what makes 32GB behave like more.",
    ),
    Part(
        key="rx_7900_xtx",
        name="Radeon RX 7900 XTX 24GB",
        kind=Kind.CONSUMER_GPU,
        vram_gb=24,
        bandwidth_gb_s=960,
        tdp_w=355,
        reference_price=700.0,
        year=2022,
        arch="RDNA3",
        slots=2.5,
        aliases=("7900 xtx", "rx 7900 xtx"),
        note="24GB at 3090 bandwidth, often cheaper than a used 3090. The "
        "difference is entirely software.",
    ),
    Part(
        key="arc_pro_b60",
        name="Intel Arc Pro B60 24GB",
        kind=Kind.PRO_GPU,
        vram_gb=24,
        bandwidth_gb_s=456,
        tdp_w=200,
        reference_price=600.0,
        year=2025,
        arch="Battlemage",
        slots=2.0,
        aliases=("arc pro b60", "arc b60"),
        note="Cheapest 24GB card sold new. Half the bandwidth of a 3090 and "
        "the thinnest software stack of the three vendors.",
    ),
    # ----------------------------------------------------------- datacenter
    Part(
        key="a100_40",
        name="A100 40GB PCIe",
        kind=Kind.DATACENTER,
        vram_gb=40,
        bandwidth_gb_s=1555,
        tdp_w=250,
        reference_price=4500.0,
        year=2020,
        arch="Ampere",
        slots=2.0,
        nvlink=True,
        aliases=("a100 40gb", "a100-40"),
        note="HBM2 bandwidth at a used-car price. Passive cooling.",
    ),
    Part(
        key="a100_80",
        name="A100 80GB PCIe",
        kind=Kind.DATACENTER,
        vram_gb=80,
        bandwidth_gb_s=1935,
        tdp_w=300,
        reference_price=9500.0,
        year=2021,
        arch="Ampere",
        slots=2.0,
        nvlink=True,
        aliases=("a100 80gb", "a100-80"),
    ),
    Part(
        key="h100_80",
        name="H100 80GB PCIe",
        kind=Kind.DATACENTER,
        vram_gb=80,
        bandwidth_gb_s=2000,
        tdp_w=350,
        reference_price=21000.0,
        year=2022,
        arch="Hopper",
        slots=2.0,
        nvlink=True,
        low_precision="fp8",
        aliases=("h100", "h100 pcie"),
    ),
    # -------------------------------------------------------------- unified
    Part(
        key="mac_studio_m3_ultra_512",
        name="Mac Studio M3 Ultra 512GB",
        kind=Kind.UNIFIED,
        vram_gb=512,
        bandwidth_gb_s=819,
        tdp_w=270,
        reference_price=14030.0,  # Terapeak sold avg, 512GB config, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m3 ultra 512", "mac studio 512gb"),
        require_all=("mac studio", "m3 ultra"),
        note="The only consumer box that holds a 671B model at Q4. Prefill is "
        "the catch -- long prompts are slow next to CUDA.",
    ),
    Part(
        key="mac_studio_m3_ultra_256",
        name="Mac Studio M3 Ultra 256GB",
        kind=Kind.UNIFIED,
        vram_gb=256,
        bandwidth_gb_s=819,
        tdp_w=270,
        reference_price=9762.0,  # Terapeak sold avg, 256GB config, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m3 ultra 256", "mac studio 256gb"),
        require_all=("mac studio", "m3 ultra"),
    ),
    Part(
        key="mac_studio_m3_ultra_96",
        name="Mac Studio M3 Ultra 96GB",
        kind=Kind.UNIFIED,
        vram_gb=96,
        bandwidth_gb_s=819,
        tdp_w=270,
        reference_price=6228.0,  # Terapeak sold avg, 96GB config, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m3 ultra 96", "mac studio 96gb"),
        require_all=("mac studio", "m3 ultra"),
        note="Base Ultra. Same 819 GB/s as the 512GB part for a third the money.",
    ),
    Part(
        key="mac_studio_m4_max_128",
        name="Mac Studio M4 Max 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=546,
        tdp_w=160,
        reference_price=3499.0,
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m4 max 128", "mac studio m4 max"),
        require_all=("mac studio", "m4 max"),
    ),
    Part(
        key="mac_studio_m3_ultra_384",
        name="Mac Studio M3 Ultra 384GB",
        kind=Kind.UNIFIED,
        vram_gb=384,
        bandwidth_gb_s=819,
        tdp_w=270,
        reference_price=11500.0,
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m3 ultra 384", "mac studio 384gb"),
        require_all=("mac studio", "m3 ultra"),
    ),
    Part(
        key="mac_studio_m2_ultra_192",
        name="Mac Studio M2 Ultra 192GB",
        kind=Kind.UNIFIED,
        vram_gb=192,
        bandwidth_gb_s=800,
        tdp_w=295,
        reference_price=5200.0,
        year=2023,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m2 ultra 192", "mac studio 192gb"),
        require_all=("mac studio", "m2 ultra"),
        note="The last generation's top box. 800 GB/s is within 3% of an M3 "
        "Ultra for roughly half the used price.",
    ),
    Part(
        key="mac_studio_m2_ultra_128",
        name="Mac Studio M2 Ultra 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=800,
        tdp_w=295,
        reference_price=3700.0,
        year=2023,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m2 ultra 128", "mac studio 128gb"),
        require_all=("mac studio", "m2 ultra"),
    ),
    Part(
        key="mac_studio_m1_ultra_128",
        name="Mac Studio M1 Ultra 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=800,
        tdp_w=370,
        reference_price=2600.0,
        year=2022,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m1 ultra 128",),
        require_all=("mac studio", "m1 ultra"),
        note="Cheapest 128GB at 800 GB/s anywhere. Four years old, so verify "
        "the machine before the price.",
    ),
    Part(
        key="mac_studio_m4_max_64",
        name="Mac Studio M4 Max 64GB",
        kind=Kind.UNIFIED,
        vram_gb=64,
        bandwidth_gb_s=546,
        tdp_w=160,
        reference_price=2300.0,
        year=2025,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m4 max 64", "mac studio 64gb"),
        require_all=("mac studio", "m4 max"),
        note="64GB and up is the 40-core GPU bin at 546 GB/s; the 36GB part "
        "is a slower 410 GB/s machine and is not this entry.",
    ),
    Part(
        key="mac_mini_m4_pro_64",
        name="Mac mini M4 Pro 64GB",
        kind=Kind.UNIFIED,
        vram_gb=64,
        bandwidth_gb_s=273,
        tdp_w=65,
        reference_price=1700.0,
        year=2024,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("m4 pro 64",),
        require_all=("mac mini", "m4 pro"),
        note="65W for 64GB. Bandwidth is DGX Spark territory, so this holds "
        "big models slowly rather than running medium ones fast.",
    ),
    # Portable unified memory. The only laptops worth hunting for this: a mobile
    # discrete GPU tops out around 24GB, but here the memory *is* the GPU
    # memory, so a 128GB MacBook holds models no $15k mobile workstation can.
    # Bandwidth is the tradeoff -- 546 GB/s against 936 on a used 3090 -- so
    # these fit big models slowly rather than small models fast.
    Part(
        key="macbook_pro_m4_max_128",
        name="MacBook Pro M4 Max 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=546,
        tdp_w=140,
        # Estimate pending a Terapeak lookup -- Apple's memory upgrades are
        # priced steeply enough that the 128GB config is what sets this, not
        # the base model.
        reference_price=5200.0,
        year=2024,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("macbook pro m4 max 128", "m4 max 128gb macbook"),
        require_all=("macbook pro", "m4 max"),
    ),
    Part(
        key="macbook_pro_m3_max_128",
        name="MacBook Pro M3 Max 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=400,
        tdp_w=140,
        reference_price=3600.0,
        year=2023,
        arch="Apple",
        usable_fraction=0.75,
        aliases=("macbook pro m3 max 128", "m3 max 128gb macbook"),
        require_all=("macbook pro", "m3 max"),
    ),
    Part(
        key="dgx_spark",
        name="NVIDIA DGX Spark (GB10) 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=273,
        tdp_w=170,
        reference_price=3619.0,  # Terapeak sold avg, 2026-08-08
        reference_basis="sold",
        year=2025,
        arch="Blackwell",
        usable_fraction=0.85,
        low_precision="fp4",
        aliases=("dgx spark", "gb10", "project digits"),
        excludes=("gx10", "ascent"),
        note="CUDA in 128GB, but 273 GB/s. Great for building and testing what "
        "you'll deploy elsewhere; slow for actually serving.",
    ),
    Part(
        key="asus_ascent_gx10",
        name="ASUS Ascent GX10 (GB10) 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=273,
        tdp_w=170,
        reference_price=2999.0,
        year=2025,
        arch="Blackwell",
        usable_fraction=0.85,
        low_precision="fp4",
        aliases=("ascent gx10", "gx10"),
        note="The same GB10 superchip as a DGX Spark in someone else's case. "
        "Cross-shop the two; they are the same machine.",
    ),
    Part(
        key="framework_desktop_128",
        name="Framework Desktop (Ryzen AI Max+ 395) 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=256,
        tdp_w=140,
        reference_price=1999.0,
        year=2025,
        arch="RDNA3.5",
        usable_fraction=0.75,
        aliases=("framework desktop",),
        require_all=("framework",),
        note="Cheapest route to 128GB. ROCm/Vulkan, so expect more friction "
        "than CUDA and no vLLM fast path.",
    ),
    Part(
        key="strix_halo_mini_128",
        name="Ryzen AI Max+ 395 mini PC 128GB",
        kind=Kind.UNIFIED,
        vram_gb=128,
        bandwidth_gb_s=256,
        tdp_w=140,
        reference_price=1700.0,
        year=2025,
        arch="RDNA3.5",
        usable_fraction=0.75,
        aliases=(
            "gmktec evo-x2",
            "beelink gtr9",
            "minisforum ms-s1 max",
            "bosgame m5",
            "ryzen ai max+ 395",
            "ryzen ai max 395",
            "strix halo",
        ),
    ),
)

BY_KEY: dict[str, Part] = {part.key: part for part in PARTS}


def get(key: str) -> Part | None:
    return BY_KEY.get(key)


def in_class(kind: str) -> list[Part]:
    """Parts matching a watchlist `class` filter. "any" means everything."""
    if kind == "any":
        return list(PARTS)
    return [part for part in PARTS if part.kind.value == kind]


def class_median_dollars_per_gb_bandwidth(kind: Kind) -> float:
    """Typical $/GB-TB/s for a category. The bandwidth-aware sibling of below.

    $/GB on its own systematically flatters slow capacity: a 128GB unified box
    at 256 GB/s scores four times better than a 3090 and generates tokens at a
    quarter of the speed. Reporting only that number recommends the wrong
    hardware to anyone who reads it quickly, which is everyone reading a push
    notification. Multiplying capacity by bandwidth prices the two things the
    machine actually has to offer, and the two figures disagreeing is itself
    the useful signal -- it means "lots of memory, slowly".

    This is a value heuristic, not tokens per second. Bandwidth predicts decode
    speed well and prefill speed badly, and neither number knows anything about
    whether the software stack you need runs on the thing.
    """
    values = sorted(part.dollars_per_gb_bandwidth for part in PARTS if part.kind is kind)
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def class_median_dollars_per_gb(kind: Kind) -> float:
    """Typical $/GB for a category, used when a part has no price history yet.

    Computed from reference prices rather than hardcoded so that retuning the
    catalog automatically retunes the fallback.
    """
    values = sorted(part.dollars_per_gb for part in PARTS if part.kind is kind)
    if not values:
        return 0.0
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
