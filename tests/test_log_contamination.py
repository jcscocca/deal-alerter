"""What the first audit of the price log turned up.

460 observations in, with references finally sourced from sold data, every
logged price could be judged against a trustworthy anchor for the first time.
37 sat above 2.5x sold. Most were real cards at asking prices nobody will pay --
noise, but honest noise. Three were not, and each is a distinct hole:

  $10,000  "RTX A6000 + Quadro Sync II Media Server / Render Node"
  $12,550  "Nvidia DGX Station RTX-6000 ADA 256GB Ram, 1.92TB NVMe AMD 7742"
  $11,857  "NVIDIA RTX PRO 5000 72GB Blackwell"

The first two are whole machines that name their card; SYSTEM_PATTERNS knew
"desktop" and "gaming pc" but not the vocabulary enterprise gear is sold under.
The third is a different card entirely -- the PRO 5000 Blackwell ships in 48GB
and 72GB, and the catalog only carries the 48GB.

This matters more than three bad rows. In two weeks the log stops being a record
and becomes the standard every verdict is measured against.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.match import match, names_multiple_models


class TestEnterpriseSystems:
    """Whole machines sold under names the filter had never seen."""

    @pytest.mark.parametrize(
        "title",
        [
            "RTX A6000 + Quadro Sync II Media Server / Render Node",
            "Nvidia DGX Station RTX-6000 ADA 256GB Ram, 1.92TB NVMe AMD 7742 Workstation",
            "Supermicro GPU Server 4U RTX A6000 Render Node 512GB",
        ],
    )
    def test_is_flagged_as_a_system(self, title: str) -> None:
        result = match(title)
        assert result.is_system, title

    def test_a_machine_whose_capacity_fits_no_variant_matches_nothing(self) -> None:
        """The DGX Station A100 advertises 320GB -- four 80GB cards pooled.
        No catalog part has that, so it never reaches the system check at all.
        Different mechanism, same outcome: nothing is logged."""
        assert match("NVIDIA DGX Station A100 320GB").part is None

    def test_a_bare_card_is_not(self) -> None:
        result = match("NVIDIA RTX A6000 48GB GDDR6 Graphics Card")
        assert result.part is not None
        assert not result.is_system

    def test_the_pro_6000_workstation_card_is_not_a_workstation(self) -> None:
        """'Workstation' is in this card's actual product name -- the pattern
        has to stay anchored to 'workstation PC' rather than the bare word."""
        result = match("NVIDIA RTX PRO 6000 Blackwell Workstation Edition 96GB")
        assert result.part is not None
        assert not result.is_system


class TestCapacityVariants:
    """A stated capacity that contradicts the part is a different card."""

    def test_the_72gb_pro_5000_is_not_the_48gb_one(self) -> None:
        result = match("NVIDIA RTX PRO 5000 72GB Blackwell Graphics card RTX PRO5000")
        assert result.part is None or result.part.vram_gb == 72

    def test_the_48gb_pro_5000_still_matches(self) -> None:
        result = match("NVIDIA RTX PRO 5000 Blackwell 48GB GDDR7")
        assert result.part is not None and result.part.key == "rtx_pro_5000_blackwell"

    def test_an_unstated_capacity_still_matches_a_discrete_card(self) -> None:
        """Unlike unified-memory boxes, a pro card that doesn't state VRAM is
        just a terse listing -- capacity is not the product."""
        result = match("NVIDIA RTX A6000 Pro-Level Ultra-High-End Graphics Card")
        assert result.part is not None and result.part.key == "rtx_a6000"

    def test_system_memory_does_not_contradict_the_card(self) -> None:
        """'64GB RAM' beside an RTX 5090 is the machine's memory, not the GPU's,
        and the listing is already caught as a system."""
        result = match(
            "HP Omen 45L Intel i9-14900KF, NVIDIA GeForce RTX 5090, 64GB RAM, 2TB SSD"
        )
        assert result.part is not None and result.part.key == "rtx_5090"


class TestAiWorkstations:
    """The second audit, 2026-08-13.

    Chasing a variation-listing bug turned up eleven rows in the log that had
    nothing to do with it: ASUS and HP towers between $3,399 and $9,199, all
    recorded as bare RTX 5090s and all dragging the part's median upward. They
    were purged only because they happened to be variation listings too. The
    same titles on an ordinary listing still scored as cards.

    Three separate holes, each of which alone was enough:

      - SYSTEM_PATTERNS anchors on "workstation PC", so "AI Workstation" -- the
        way every builder on eBay writes it -- read as a card.
      - CPU_RE required Intel's "Core" prefix, and sellers write "ULTRA 9 285K".
      - STORAGE_RE wanted the capacity adjacent to the memory word, so "512GB
        ECC RAM" on a $25,400 Threadripper box didn't count as memory.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "ULTRA 9 285K AI Workstation ASUS ROG Astral RTX 5090 128GB DDR5 4TB SSD WIFI 7!",
            "HP OMEN 45L AI Workstation/Gaming Ultra 9 285K RTX 5090 128GB DDR5 READY!",
            "ULTRA 9 285K AI Workstation ASUS ROG RTX 5090 - 128GB DDR5 6TB SSD GEN5 - WiFi 7",
            "Threadripper Pro 7995WX 512GB ECC RAM RTX A6000 ADA LLM AI Learning Workstation",
            "Core Ultra 9 285K Gaming Ai Workstation PC - RTX 5090 - 128GB DDR5 -4TB SSD",
        ],
    )
    def test_is_flagged_as_a_system(self, title: str) -> None:
        result = match(title, price=4000.0)
        assert result.is_system, title

    @pytest.mark.parametrize(
        "title",
        [
            "NVIDIA RTX PRO 6000 Blackwell Workstation Edition 96GB",
            "RTX PRO 5000 Blackwell 48GB GDDR7",
            "PNY NVIDIA RTX A6000 48GB GDDR6 Professional Graphics Card",
            "MSI GeForce RTX 5090 Ventus 3X OC 32GB GDDR7",
        ],
    )
    def test_a_bare_card_is_untouched(self, title: str) -> None:
        result = match(title, price=4000.0)
        assert result.part is not None, title
        assert not result.is_system, title


class TestVendorPartNumbers:
    """A part number is not a second card.

    The model-enumeration guard was widened to datacenter SKUs on 2026-08-13
    and, written as a letter-plus-three-digits shape, immediately swallowed six
    real RTX 3090s: MSI stamps its part number in the title and "912-V388-054"
    read as a V-series card. Two models named means the price is unattributable
    and the row never reaches the log -- so a shape this loose would have held
    the most-logged part in the catalog out of its own distribution.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "MSI GeForce RTX 3090 GAMING X TRIO 24GB GDDR6X Graphics Card 912-V388-054",
            "MSI Gaming Suprim X GeForce RTX 3090 24GB GDRR6X PCIe 4.0 (912-V388-010)",
            "Dell Nvidia GeForce RTX 3090 24GB - MS-V388 - GDDR6X - Tested & Working",
        ],
    )
    def test_a_part_number_is_not_a_model(self, title: str) -> None:
        assert not names_multiple_models(title), title
        result = match(title, price=800.0)
        assert result.part is not None and result.part.key == "rtx_3090"
        assert not result.is_bundle

    def test_a_real_datacenter_menu_is_still_caught(self) -> None:
        title = "ASUS ESC8000A-E12 4U 8 GPU Server For NVIDIA A100 H100 80GB, AMD EPYC"
        assert names_multiple_models(title)


class TestAppleCoreCounts:
    """Apple writes core counts the way everyone else writes capacity.

    "Mac Studio M3 Ultra 512GB Unified Memory 32C 80G 16TB SSD" is a 32-core
    CPU and an 80-core GPU; four live listings in one run parsed the 80G as
    80GB. Nothing collides today -- the M3 Ultra ships 60 or 80 GPU cores and
    no catalog capacity is either -- but a config that did would have quietly
    vetoed a correct match.
    """

    def test_the_core_count_does_not_become_a_capacity(self) -> None:
        result = match(
            "Apple Mac Studio M3 Ultra 512GB Unified Memory 32C 80G 16TB SSD | AppleCare",
            price=21499.99,
        )
        assert result.part is not None
        assert result.part.key == "mac_studio_m3_ultra_512"

    def test_a_real_capacity_still_decides(self) -> None:
        result = match("Apple Mac Studio M3 Ultra 28C 60G 96GB 1TB", price=3600.0)
        assert result.part is not None
        assert result.part.key == "mac_studio_m3_ultra_96"
