"""Four contaminated rows found by auditing the committed log on 2026-08-17.

Each one is a different hole, and each was the *cheapest* observation in its
bucket -- which is the expensive kind of wrong. A mismatch that reads as
expensive gets discarded as noise; a mismatch that reads as cheap sets the
part's floor, leads the digest, and is the thing you get woken up about.

The audit that found them: of 1,417 logged observations, exactly 4 sat below
the old STRONG alert line, and all 4 are here.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.match import match


class TestMaxQIsNotTheWorkstationCard:
    """300W and 2-slot against 600W and 3-slot, sharing every other word.

    The Max-Q entry existed the whole time. Its aliases just required the words
    to be adjacent, and no seller writes them that way -- the capacity and
    memory type land in between. So every Max-Q card was recorded against the
    Workstation entry, corrupting both distributions, and the one part in the
    catalog that fits a normal tower would have been recommended as a 600W one.
    """

    MAXQ_TITLES = (
        "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 Max-Q Edition New Bulk Packaging",
        "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition",
        "PNY NVIDIA RTX Pro 6000 Blackwell Max-Q 96GB GDDR7 Workstation GPU - Bulk",
        "NVIDIA RTX PRO 6000 Blackwell Max-Q Turbo Workstation Edition 300W",
        "Nvidia RTX PRO 6000 Blackwell MaxQ Workstation 96GB GDDR7 GPU Dell P/N",
    )
    WORKSTATION_TITLES = (
        "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 Workstation Edition BULK OEM",
        "NVIDIA RTX PRO 6000 Blackwell Workstation Edition Professional Graphics Card",
        "PNY NVIDIA RTX PRO 6000 Blackwell Workstation 96GB GDDR7 Graphics Card",
    )

    @pytest.mark.parametrize("title", MAXQ_TITLES)
    def test_max_q_lands_on_the_max_q_entry(self, title: str) -> None:
        result = match(title, price=13000.0)
        assert result.part is not None
        assert result.part.key == "rtx_pro_6000_blackwell_maxq"

    @pytest.mark.parametrize("title", MAXQ_TITLES)
    def test_max_q_is_not_read_as_two_cards(self, title: str) -> None:
        """The exclusion has to hold in find_all_parts too. Matching the Max-Q
        entry while the base entry still counts as present would make every
        Max-Q listing a two-GPU bundle, which is never logged."""
        assert not match(title, price=13000.0).is_bundle

    @pytest.mark.parametrize("title", WORKSTATION_TITLES)
    def test_the_600w_card_still_matches_itself(self, title: str) -> None:
        result = match(title, price=13000.0)
        assert result.part is not None
        assert result.part.key == "rtx_pro_6000_blackwell"


class TestWorkstationBuildIsNotABareCard:
    def test_xeon_workstation_is_a_system(self) -> None:
        """Logged at $21,953.97/unit as a bare RTX PRO 6000. The ai-workstation
        pattern wanted those two words adjacent and "Machine Learning" sits
        between them; with no RAM or SSD quoted, the Xeon had nothing to pair
        with either."""
        result = match(
            "Intel Xeon w7-3565X 2x RTX PRO 6000 Blackwell AI/Machine Learning "
            "Workstation",
            price=43907.94,
        )
        assert result.is_system, "a machine, not a card"

    @pytest.mark.parametrize(
        "title",
        [
            # "Workstation" is in this card's actual product name, and "AI GPU"
            # is how half the pro cards on eBay advertise themselves. Neither
            # may condemn a listing without a CPU beside it.
            "NVIDIA RTX PRO 6000 96GB Blackwell Workstation Edition AI GPU Graphics Card",
            "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 Workstation Edition New Retail",
            "NVIDIA RTX PRO 6000 96GB Blackwell Server Edition AI GPU Graphics Cards",
        ],
    )
    def test_a_bare_card_is_not_condemned_by_its_own_name(self, title: str) -> None:
        assert not match(title, price=14000.0).is_system


class TestVramIsNotSystemMemory:
    """The third "AI Workstation" card from the 2026-09-17 digest.

    Three bare cards wore the builders' phrase that day. The card word added on
    2026-09-21 rescued the two that say "GPU" or "Graphics Card"; this one --
    "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 ECC AI Workstation", $3,999,
    eBay 188939006524 -- never names a card at all, so the phrase went
    unopposed and it led the digest as a whole machine undercutting the loose
    card. Nothing was logged and no receipt was written: the cheapest RTX PRO
    6000 asking price of that week is absent from state entirely.

    What contradicts the phrase is "96GB GDDR7". GDDR and HBM are memory only a
    card carries; a machine quotes DDR5 and an SSD, which STORAGE_RE already
    reads as the machine winning.
    """

    def test_a_card_quoting_only_its_vram_is_a_card(self) -> None:
        result = match(
            "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 ECC AI Workstation",
            price=3999.0,
        )
        assert result.part is not None
        assert result.part.key == "rtx_pro_6000_blackwell"
        assert not result.is_system, "a card, not a machine"

    @pytest.mark.parametrize(
        "title",
        [
            "ULTRA 9 285K AI Workstation ASUS ROG Astral RTX 5090 128GB DDR5 4TB SSD",
            "Intel ULTRA 9 285K AI Workstation PC - NVIDIA RTX 5090 64GB DDR5 4TB SSD WIFI 7!",
            "Ryzen 7 9850X3D AI Workstation PC RTX 5090 128GB DDR5 2TB Gen4 WiFi CreatorPC",
            "Intel Xeon w7-3565X 2x RTX PRO 6000 Blackwell AI/Machine Learning Workstation",
            "HP Omen 45L Intel i9-14900KF, NVIDIA GeForce RTX 5090, 64GB RAM, 2TB SSD",
            # A tower may quote its card's VRAM alongside its own memory. The
            # DDR5 and the SSD still decide.
            "ULTRA 9 285K AI Workstation ASUS ROG Astral RTX 5090 32GB GDDR7 128GB DDR5 4TB SSD",
            # ...and one that quotes neither still has its CPU beside the
            # build word.
            "Ryzen 9 9950X AI Workstation RTX 5090 32GB GDDR7",
        ],
    )
    def test_a_machine_is_still_a_machine(self, title: str) -> None:
        assert match(title, price=4000.0).is_system, title


class TestMobileModuleIsNotTheDesktopCard:
    def test_dell_pro_max_laptop_module_is_dropped(self) -> None:
        """$3,000 against the 48GB desktop card's $4,500 reference, and the
        cheapest observation in that bucket. "18" is a screen size written
        without an inch mark, so no existing mobile pattern saw it."""
        result = match(
            "nvidia rtx pro 5000 blackwell for dell pro max 18 plus", price=3000.0
        )
        assert result.part is None

    def test_legion_9i_laptop_is_dropped(self) -> None:
        """Logged 2026-09-20 at $4,800 as a new desktop RTX 5090 -- the listing
        sits in eBay's PC Laptops category. Two holes, each enough alone: the
        family pattern wanted a bare digit and Lenovo writes "9i", and the
        screen size carries a double prime (U+2033) rather than an inch mark."""
        result = match("Legion 9i Gen 10 Intel (18″) with RTX 5090", price=4800.0)
        assert result.part is None

    @pytest.mark.parametrize(
        "title",
        [
            "Lenovo Legion 9i Gen 10 with RTX 5090",
            "Gen 10 Intel (18″) with RTX 5090",
        ],
    )
    def test_each_hole_alone_is_closed(self, title: str) -> None:
        assert match(title, price=4800.0).part is None

    def test_a_desktop_5090_still_matches(self) -> None:
        result = match("MSI GeForce RTX 5090 32GB Gaming Trio OC", price=3500.0)
        assert result.part is not None and result.part.key == "rtx_5090"

    def test_the_desktop_card_still_matches(self) -> None:
        result = match(
            "NVIDIA RTX PRO 5000 Blackwell 48GB GDDR7 PCIe 5.0 Graphics Card",
            price=6500.0,
        )
        assert result.part is not None
        assert result.part.key == "rtx_pro_5000_blackwell"

    def test_a_macbook_still_matches_its_own_catalog_entry(self) -> None:
        """The mobile filter exempts unified parts, so adding "macbook" to it
        must not cost the catalog its MacBook Pro entries."""
        result = match(
            "MacBook Pro 16 2024 M4 Max 128GB 4TB Space Black", price=4650.0
        )
        assert result.part is not None
        assert result.part.key == "macbook_pro_m4_max_128"


class TestBlankTitleIsNotAMatch:
    """40.3% of the log carries no title at all.

    A storage bug, fixed forward on 2026-08-13, but the rows remain and cannot
    be audited for mismatch even in hindsight -- including a $2,686 A100 40GB
    that would have been the tool's only push-worthy alert. A title is the only
    evidence a listing is what its part key says it is.
    """

    @pytest.mark.parametrize("title", ["", "   ", "\n\t"])
    def test_blank_titles_are_refused(self, title: str) -> None:
        result = match(title, price=2686.0)
        assert result.part is None
        assert result.junk


class TestLockedAndPreProductionListingsAreNotTheProduct:
    """Found by the 2026-09-24 deal audit.

    An MDM-enrolled Mac still belongs to the company that enrolled it: the
    bypass holds only until the SSD is erased, then the lock comes back. The
    seller's own words (318910790995): "the MDM will appear again IF you
    factory reset". It priced at $3,500 against ~$4,200 for a clean M2 Ultra
    128GB and got a STRONG digest slot. An engineering sample is a
    pre-production board sold without the retail card's firmware or support.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "2023 Mac Studio 24 Cores, 60 Cores GPU M2 Ultra,128gb Ram,1Tb. MDM Bypass *READ*",
            "2025 Mac Studio (1TB SSD, M4 Max, 128GB )16 Core CPU , 40 Core GPU, MDM , READ",
            "AMD Radeon PRO W7900 48Gb GDDR6 Navi31 Eng Sample Video Card",
            "NVIDIA RTX 6000 Ada 48GB Engineering Sample",
        ],
    )
    def test_they_are_dropped(self, title: str) -> None:
        assert match(title, price=3500).junk

    @pytest.mark.parametrize(
        "title,part",
        [
            ("Apple Mac Studio M2 Ultra 128GB 1TB - No MDM, Clean Title", "mac_studio_m2_ultra_128"),
            ("Mac Studio M4 Max 128GB 1TB Not MDM Locked", "mac_studio_m4_max_128"),
            ("Mac Studio M4 Max 128GB 1TB, MDM-free, iCloud off", "mac_studio_m4_max_128"),
            ("AMD Radeon PRO W7900 48GB GDDR6 Retail Graphics Card", "radeon_pro_w7900"),
        ],
    )
    def test_a_seller_saying_it_is_clean_still_matches(self, title: str, part: str) -> None:
        result = match(title, price=4000)
        assert not result.junk
        assert result.part.key == part
