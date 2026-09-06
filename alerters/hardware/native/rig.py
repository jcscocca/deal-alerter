"""The machines you already own, and what a candidate part would change.

This is the module that makes the difference between "that's a cheap 3090" and
"that's a cheap 3090 *and it takes you from 18GB to 42GB, which is the first
time you can hold a 70B at Q4*". The Steam project answered "is this discount
good for this game"; the hardware equivalent has to answer "is this purchase
good for this cluster", and that needs to know what the cluster is.

Edit NODES to match reality if anything changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Part


@dataclass(frozen=True)
class Node:
    name: str
    role: str
    vram_gb: float
    bandwidth_gb_s: int
    arch: str
    # Only counts toward a pooled total if the accelerators can actually be
    # used together. Separate boxes on a LAN cannot, for tensor parallelism.
    host: str


NODES: tuple[Node, ...] = (
    Node("RTX 3080 (Gaming Z Trio)", "planner/architect", 10, 760, "Ampere", "desktop"),
    Node("RTX 2080 (Zotac)", "planner/architect", 8, 448, "Turing", "desktop"),
    Node("RTX 3500 Ada (P16 Gen 2)", "orchestrator/coder", 12, 432, "Ada", "thinkpad"),
    Node("M4 Pro (MacBook Pro)", "reviewer/loop-breaker", 18, 273, "Apple", "macbook"),
)

# The box a new card would actually go into.
TARGET_HOST = "desktop"
TARGET_HOST_DESC = "Z790 AORUS PRO X / i7-14700 / 64GB / EVGA SuperNOVA 1000 GT"
PSU_WATTS = 1000
# i7-14700 peaks near 220W under all-core load; add board, drives and fans.
BASE_SYSTEM_DRAW_W = 300
# The top x16 slot is the only one with full bandwidth. The middle slot is PCH
# x4, which is fine for inference weights that stay resident but painful for
# anything that streams layers across the bus.
FULL_SPEED_SLOTS = 1
TOTAL_USABLE_SLOTS = 2


def host_vram_gb(host: str = TARGET_HOST) -> float:
    return sum(node.vram_gb for node in NODES if node.host == host)


def cluster_vram_gb() -> float:
    """Every accelerator you own, summed. Aspirational, not addressable."""
    return sum(node.vram_gb for node in NODES)


# Reference TDPs for the cards currently in the target host. Kept here rather
# than in the catalog because these are installed hardware, not things we hunt.
INSTALLED_GPU_TDP_W = {
    "RTX 3080 (Gaming Z Trio)": 350,
    "RTX 2080 (Zotac)": 225,
}


def host_draw_w(host: str = TARGET_HOST) -> int:
    """Current GPU draw on the target host, for PSU headroom math."""
    return sum(
        INSTALLED_GPU_TDP_W.get(node.name, 0)
        for node in NODES
        if node.host == host
    )


# --------------------------------------------------------------- model ladder

# Bytes per parameter at each quantisation, including the format's own overhead
# (scales, zero-points, and the handful of tensors llama.cpp keeps at higher
# precision). Q4 is pitched at the lean end of the family -- Q4_K_S / IQ4_XS
# rather than Q4_K_M -- because that's what people actually reach for when a
# model only just fits, which is exactly the case this math is deciding.
BYTES_PER_PARAM = {
    "Q4": 0.55,
    "Q5": 0.70,
    "Q8": 1.08,
    "fp16": 2.00,
}

# Memory left free for KV cache, activations and the compute graph. A flat
# percentage is wrong at both ends: it reserves a pointless 100GB on a 512GB
# Mac and starves a 12GB card. It also overstates modern KV cache badly --
# every model on the ladder uses grouped-query attention, so 32k context on a
# 70B costs single-digit GB, not the ~40GB that multi-head attention would.
# So: 15%, capped at 6GB.
CONTEXT_RESERVE_FRACTION = 0.15
CONTEXT_RESERVE_CAP_GB = 6.0


def usable_for_weights(vram_gb: float) -> float:
    """Memory available for model weights after context overhead."""
    reserve = min(vram_gb * CONTEXT_RESERVE_FRACTION, CONTEXT_RESERVE_CAP_GB)
    return max(vram_gb - reserve, 0.0)


@dataclass(frozen=True)
class Model:
    name: str
    params_b: float
    note: str = ""


# What you'd actually reach for, smallest to largest. Enough rungs that the
# "what does this unlock" sentence can say something specific -- a ladder that
# jumps 30B to 70B to 235B makes every mid-size card sound identical.
LADDER: tuple[Model, ...] = (
    Model("Qwen3 8B", 8, "fits anywhere; fine for routing and cleanup"),
    Model("Qwen3 14B", 14, ""),
    Model("Qwen3 32B", 32, "the sweet spot for a single 24GB card"),
    Model("Qwen3 30B-A3B", 30, "MoE, only 3B active -- fast even when tight"),
    Model("Llama 3.3 70B", 70, "the standard heavy reasoner"),
    Model("gpt-oss 120B", 120, "MoE, ~5B active"),
    Model("Qwen3 235B-A22B", 235, "MoE, frontier-adjacent reasoning"),
    Model("Llama 3.1 405B", 405, ""),
    Model("DeepSeek-V3 / R1 671B", 671, "MoE, 37B active"),
)
# Sorted by size so "largest that fits" is a scan from the top.
_LADDER_BY_SIZE = tuple(sorted(LADDER, key=lambda m: m.params_b))


def largest_model_at(vram_gb: float, quant: str = "Q4") -> Model | None:
    """Biggest ladder entry that fits in `vram_gb`, leaving room for context."""
    budget = usable_for_weights(vram_gb)
    per_param = BYTES_PER_PARAM[quant]
    fits = [m for m in _LADDER_BY_SIZE if m.params_b * per_param <= budget]
    return fits[-1] if fits else None


def fits_model(vram_gb: float, model: Model, quant: str = "Q4") -> bool:
    return model.params_b * BYTES_PER_PARAM[quant] <= usable_for_weights(vram_gb)


# ------------------------------------------------------------------ fit check


@dataclass
class Fit:
    """Whether the part physically goes in, and what it would cost to make it."""

    ok: bool
    notes: list[str]

    @property
    def summary(self) -> str:
        return " ".join(self.notes) if self.notes else "Drops straight in."


def check_fit(part: Part, *, psu_headroom_w: int = 150, replace_both: bool = True) -> Fit:
    """Can this go in the desktop, and what has to change if not?

    `replace_both` models the realistic upgrade: the 3080 and 2080 come out and
    the new part goes in. Keeping them installed alongside a 575W card is what
    actually blows the power budget, so the answer differs a lot.
    """
    notes: list[str] = []
    ok = True

    if part.kind.value == "unified":
        return Fit(
            True,
            [
                "Standalone box -- becomes a fourth node rather than going in "
                "the tower, so no PSU or slot constraints apply."
            ],
        )

    existing_gpu_w = 0 if replace_both else host_draw_w()
    total = BASE_SYSTEM_DRAW_W + existing_gpu_w + part.tdp_w
    budget = PSU_WATTS - psu_headroom_w
    if total > budget:
        ok = False
        notes.append(
            f"Needs about {total}W against a {PSU_WATTS}W PSU "
            f"(keeping {psu_headroom_w}W headroom) -- PSU upgrade required."
        )
    else:
        notes.append(f"~{total}W total, within the {PSU_WATTS}W PSU.")

    if part.slots and part.slots > 3.0:
        notes.append(f"{part.slots}-slot card -- check case clearance.")

    if part.kind.value == "datacenter":
        notes.append(
            "Passively cooled: no fan of its own, so it needs directed chassis "
            "airflow. Desktop cases generally cannot do this."
        )

    if part.arch not in {"Ampere"} and not replace_both:
        notes.append(
            f"{part.arch} alongside Ampere+Turing still can't tensor-parallel "
            "cleanly -- treat it as a single-card node."
        )

    return Fit(ok, notes)


def capability_gain(part: Part) -> tuple[float, float, str]:
    """(before_gb, after_gb, one sentence on what it unlocks).

    "After" assumes the new part replaces the desktop's two cards rather than
    joining them, because a Turing card in the pool caps you at fp16 anyway.
    """
    before = host_vram_gb()
    after = part.usable_vram_gb

    old_best = largest_model_at(before)
    new_best = largest_model_at(after)

    if new_best is None:
        return before, after, f"Still under {_LADDER_BY_SIZE[0].name} at Q4."

    if old_best is None:
        return (
            before,
            after,
            f"First time you can hold {new_best.name} at Q4 -- today the desktop "
            f"tops out below {_LADDER_BY_SIZE[0].name}.",
        )

    if new_best.name == old_best.name:
        return (
            before,
            after,
            f"Same tier you can already run ({old_best.name} at Q4), but with "
            f"far more context headroom.",
        )

    return (
        before,
        after,
        f"Takes the desktop from {old_best.name} to {new_best.name} at Q4.",
    )
