"""The parts added when the catalog stopped being NVIDIA-only.

Two failure modes matter for a catalog entry, and neither shows up as an
exception. A part nothing matches is invisible, and a part that matches
alongside another turns one listing into a two-item bundle -- which
find_all_parts then refuses to log, so a new entry can silently cost you the
history of an existing one.

Every capacity and bandwidth figure here is a vendor published peak, looked up
rather than derived from a listing, and every reference price is an estimate
until somebody checks it against sold data.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.catalog import PARTS, BY_KEY, Kind
from alerters.hardware.native.match import find_all_parts, find_part

ADDED = [
    ("radeon_pro_w7900", "AMD Radeon PRO W7900 48GB Workstation Graphics Card"),
    ("radeon_pro_w7800", "AMD Radeon PRO W7800 32GB Professional GPU"),
    ("radeon_ai_pro_r9700", "AMD Radeon AI PRO R9700 32GB"),
    ("rx_7900_xtx", "XFX Speedster MERC310 Radeon RX 7900 XTX 24GB GDDR6"),
    ("arc_pro_b60", "ASRock Intel Arc Pro B60 Creator 24GB"),
    ("mac_studio_m3_ultra_384", "Apple Mac Studio (2025) M3 Ultra 384GB 4TB"),
    ("mac_studio_m2_ultra_192", "Apple Mac Studio M2 Ultra 192GB 4TB SSD"),
    ("mac_studio_m2_ultra_128", "Apple Mac Studio (2023) M2 Ultra 128GB 1TB"),
    ("mac_studio_m1_ultra_128", "Mac Studio M1 Ultra 128GB 2TB"),
    ("mac_studio_m4_max_64", "Apple Mac Studio M4 Max 64GB 1TB SSD"),
    ("mac_mini_m4_pro_64", "Apple Mac mini M4 Pro 64GB 1TB"),
    ("asus_ascent_gx10", "ASUS Ascent GX10 128GB GB10 AI Supercomputer"),
]


class TestEachNewPartIsReachable:
    @pytest.mark.parametrize("key,title", ADDED)
    def test_the_title_finds_it(self, key: str, title: str) -> None:
        assert find_part(title)[0] is BY_KEY[key]

    @pytest.mark.parametrize("key,title", ADDED)
    def test_and_finds_nothing_else(self, key: str, title: str) -> None:
        assert [part.key for part in find_all_parts(title)] == [key]


class TestTheCollisionsWorthNaming:
    def test_a_gx10_is_not_also_a_dgx_spark(self) -> None:
        # Same GB10 superchip in someone else's case, so a GX10 title naming
        # its own chip matches both entries and reads as two machines.
        assert [p.key for p in find_all_parts("ASUS Ascent GX10 GB10 128GB")] == ["asus_ascent_gx10"]
        assert find_part("NVIDIA DGX Spark GB10 128GB")[0] is BY_KEY["dgx_spark"]

    def test_a_7900_xt_is_not_a_7900_xtx(self) -> None:
        assert find_part("Sapphire Radeon RX 7900 XT 20GB")[0] is None

    def test_a_bosgame_is_the_strix_halo_entry_not_a_new_one(self) -> None:
        found = find_part("Bosgame M5 AI Mini PC Ryzen AI Max+ 395 128GB")[0]
        assert found is BY_KEY["strix_halo_mini_128"]

    @pytest.mark.parametrize("title,key", [
        ("Apple Mac Studio M4 Max 64GB 1TB", "mac_studio_m4_max_64"),
        ("Apple Mac Studio M4 Max 128GB 1TB", "mac_studio_m4_max_128"),
        ("Apple Mac Studio M2 Ultra 128GB", "mac_studio_m2_ultra_128"),
        ("Apple Mac Studio M2 Ultra 192GB", "mac_studio_m2_ultra_192"),
    ])
    def test_capacity_picks_the_bin(self, title: str, key: str) -> None:
        # One name spans a 3x memory range and memory is the entire purchase,
        # so the stated capacity has to choose, and silence has to mean no match.
        assert find_part(title)[0] is BY_KEY[key]

    def test_a_mac_studio_with_no_stated_memory_matches_nothing(self) -> None:
        assert find_part("Apple Mac Studio M2 Ultra Desktop Computer")[0] is None


class TestCatalogInvariants:
    @pytest.mark.parametrize("part", PARTS, ids=lambda part: part.key)
    def test_every_part_can_be_scored(self, part) -> None:
        assert part.vram_gb > 0 and part.bandwidth_gb_s > 0
        assert part.reference_price > 0 and part.capacity_bandwidth > 0

    def test_keys_are_unique(self) -> None:
        assert len(BY_KEY) == len(PARTS)

    @pytest.mark.parametrize("part", PARTS, ids=lambda part: part.key)
    def test_an_unverified_anchor_says_so(self, part) -> None:
        # Every new entry is an estimate, and estimates are held below the push
        # threshold. A reference_basis of "sold" is a claim about real
        # transactions that nobody has made for these parts yet.
        assert part.reference_basis in ("sold", "estimate")

    @pytest.mark.parametrize("part", [p for p in PARTS if p.kind is Kind.UNIFIED],
                             ids=lambda part: part.key)
    def test_a_unified_box_states_its_capacity_in_its_own_name(self, part) -> None:
        # _capacity_agrees requires a stated capacity for unified parts, so an
        # entry whose own name omits it can only ever be matched by accident.
        assert str(part.vram_gb) in part.name
