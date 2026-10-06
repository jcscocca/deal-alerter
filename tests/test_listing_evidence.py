"""Reconstructed fixtures from the reported Oct 4 listing excerpts, not snapshots."""

import pytest

from alerters.hardware.native.match import match


SERVER = "ASUS ESC8000A-E12 4U 8 GPU Server For NVIDIA A100 H100 80GB , AMD EPYC 9004 CPU"


@pytest.mark.parametrize("title,body", [
    # eBay 960010926668: the bridge was tested between cards, not sold with them.
    ("NVIDIA GeForce RTX NVLink HB Bridge 4-Slot P3657 RTX 3090/3090Ti Tested",
     "Tested between two RTX 3090 cards. Cards are not included."),
    # eBay 188936957585 / 318628291875: item specifics describe empty hardware.
    (SERVER, "GPU: None\nProcessor: None\nMemory: None\nHDD: None"),
    ("GPU Server with NVIDIA H100 80GB", "Graphics cards not included."),
    ("RTX 3090 Ti 24GB", "GPU: None"),
    ("Replacement cooler for NVIDIA RTX 3090 GPU-not-included", ""),
    ("Compute server compatible with H100 80GB", ""),
    ("Compute server tested with H100 80GB", ""),
    ("Compute server pictured with H100 80GB", ""),
])
def test_excluded_or_unsupported_inventory_has_no_part(title, body):
    result = match(title, body=body, price=1199.99)
    assert result.part is None


def test_compatibility_only_server_is_unknown_without_description():
    assert match(SERVER, price=5549).part is None


@pytest.mark.parametrize("bridge", ["NVLink bridge", "NVLink HB bridge"])
def test_actual_card_with_included_bridge_survives(bridge):
    result = match(f"RTX3090Ti24GB with {bridge} included", price=1199.99)
    assert result.part.key == "rtx_3090_ti"
    assert result.quantity == 1
    assert not result.junk


@pytest.mark.parametrize("description", ["No drivers installed.", "No GPU drivers installed."])
def test_no_drivers_is_not_no_card(description):
    result = match("RTX 3090 24GB", body=description + " Tested working.", price=700)
    assert result.part.key == "rtx_3090"
    assert result.mining_score == 0


def test_nonworking_body_retains_parts_condition_for_downstream_veto():
    result = match("NVIDIA RTX3090 24GB", body="For parts, not working", price=700)
    assert result.part.key == "rtx_3090"
    assert result.condition == "parts"


def test_selected_populated_server_retains_per_card_capacity():
    result = match(SERVER, body="GPU: 2x H100 80GB\nProcessor: AMD EPYC", price=30000)
    assert result.part.key == "h100_80"
    assert result.part.vram_gb == 80
    assert result.is_system
    assert not result.is_bundle
    assert result.quantity == 1  # One machine purchased, not a price for each card.
    assert result.unit_price == 30000


def test_cpu_compatibility_does_not_hide_installed_server_gpus():
    result = match(
        "Supermicro 4U GPU Server for AMD EPYC 7003 with 4x NVIDIA A100 80GB installed",
        price=30000,
    )
    assert result.part.key == "a100_80"
    assert result.is_system
    assert not result.is_bundle
    assert result.quantity == 1


@pytest.mark.parametrize("title", [
    "Gaming PC i7-4790 RTX3090 24GB",
    "Gaming PC i7-4790 RTX 3090 24GB",
    "Xeon E5-2690 RTX3090 24GB workstation",
    "Xeon E5-2690 RTX 3090 24GB workstation",
])
def test_explicit_cpu_model_is_not_a_second_gpu(title):
    result = match(title, price=1000)
    assert result.part.key == "rtx_3090"
    assert result.is_system
    assert not result.is_bundle


def test_real_distinct_gpu_models_in_system_remain_a_bundle():
    result = match("Gaming PC i7-4790 RTX3090 24GB + RTX4090 24GB", price=2000)
    assert result.is_system
    assert result.is_bundle


def test_contradictory_populated_server_does_not_claim_cards():
    result = match(SERVER, body="GPU: 2x H100 80GB\nGPUs not included", price=5549)
    assert result.part is None


@pytest.mark.parametrize("body", [
    "GPU: RTX 3060 12GB",
    "GPU: RTX 4090 24GB",
    "GPU: H100 80GB\nGPU: A100 80GB",
    "GPU: H100 80GB optional",
])
def test_server_configuration_cannot_fall_back_to_conflicting_title(body):
    assert match("GPU Server with NVIDIA H100 80GB", body=body, price=10000).part is None


def test_standalone_a100_server_graphics_board():
    # eBay 287617703866 wording reconstructed; server describes card use.
    result = match("NVIDIA A100 80GB PCIe Server Graphics Board", price=8000)
    assert result.part.key == "a100_80"
    assert not result.is_system


def test_gpu_pulled_from_prebuilt_is_one_used_card():
    # Reddit 1wryn4v: another item precedes the GPU in this reconstructed post.
    result = match(
        "[USA] [H] MSI RTX 3090 Ti pulled from prebuilt, Switch bundle [W] PayPal",
        body="Switch bundle BNIB - $400\nMSI RTX 3090 Ti - $1400 shipped, pulled from prebuilt",
    )
    assert result.part.key == "rtx_3090_ti"
    assert result.price == 1400
    assert result.condition == "used"
    assert result.quantity == 1
    assert not result.is_system
    assert result.mining_score == 0


def test_rich_multi_sale_title_uses_gpu_row_not_other_items_capacity():
    # Reddit 1wryn4v: reconstructed from URL title and supplied body excerpts.
    result = match(
        "[USA-TX][H] 3090 Ti, 4080, 4070 Ti Super, 7950X3D+MOBO+64GB [W] PayPal",
        body="MSI 3090 Ti - $1400 shipped, pulled from prebuilt\nRTX4080 - $1800\n"
             "7950X3D motherboard64GB combo - $900",
    )
    assert result.part.key == "rtx_3090_ti"
    assert result.price == 1400
    assert result.condition == "used"
    assert result.mining_score == 0
    assert not result.is_system
    assert result.is_bundle


def test_gpu_stock_does_not_borrow_other_items_bnib_or_divide_price():
    # Reddit 1wrybps: stock quantity in the body does not promise a priced lot.
    result = match(
        "[USA] [H] RTX 5090 FE, BNIB Switch 2 bundle, Ryzen 7 [W] Cash",
        body="3x RTX5090FE - $6300 local pickup only at a bank; tested, removed from PC\n"
             "BNIB Switch 2 bundle - $500\nRyzen 7 - $200",
    )
    assert result.part.key == "rtx_5090"
    assert result.price == result.unit_price == 6300
    assert result.condition == "used"
    assert result.quantity == 1
    assert result.mining_score == 0
    assert result.is_bundle  # No claim that $6300 buys one card or all three.


def test_explicit_per_card_price_for_body_stock_is_attributable():
    result = match("[USA] [H] RTX 5090 FE [W] Cash", body="3x RTX5090FE - $6300 each")
    assert result.part.key == "rtx_5090"
    assert result.price == result.unit_price == 6300
    assert result.quantity == 1
    assert not result.is_bundle


def test_explicit_lot_and_mining_evidence_still_count():
    result = match("Lot of 3 RTX 3090 mining farm cards - $1800")
    assert result.quantity == 3
    assert result.unit_price == 600
    assert result.mining_risk == "high"


def test_two_prices_for_same_card_remain_unattributed():
    result = match("[USA] [H] RTX 5090 [W] Cash", body="RTX 5090 FE $6300\nRTX 5090 MSI $6000")
    assert result.part.key == "rtx_5090"
    assert result.price is None


def test_excluded_inventory_never_enters_assessments_report_or_history(tmp_path):
    from datetime import datetime, timezone

    from dealcore.types import Listing
    from tests.hardware_pipeline import evaluate, logged, plugin

    listings = [
        Listing("188936957585", "ebay", SERVER, "https://example.test/server",
                datetime.now(timezone.utc), price=5549, body="GPU: None\nProcessor: None"),
        Listing("960010926668", "ebay", "NVIDIA NVLink HB Bridge RTX 3090/3090Ti Tested",
                "https://example.test/bridge", datetime.now(timezone.utc), price=1199.99,
                body="Tested between two cards. Cards not included."),
    ]
    hardware = plugin(tmp_path)
    try:
        assert all(hardware.prepare(row) is None for row in listings)
    finally:
        hardware.close()
    assessments, matched = evaluate(tmp_path, listings)
    assert assessments == []
    assert matched == 0
    assert logged(tmp_path) == 0
    assert not (tmp_path / "report-hardware.html").exists()
