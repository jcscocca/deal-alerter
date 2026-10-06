"""Render illustrative alerts without network access, history writes or sending.

    python scripts/preview_desktop_profile.py
"""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alerters.hardware.prebuilt import Offer
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, offer_listing
from dealcore.report import render_html
from dealcore.types import Report


def main():
    now = datetime.now(timezone.utc)
    examples = [
        (3599, {"RAM":"64GB DDR5 (2 x 32GB)", "Memory Slots":"4", "Maximum Memory":"128GB"}),
        (2799, {"RAM":"32GB DDR5 (2 x 16GB)", "Memory Slots":"4", "Maximum Memory":"128GB"}),
        (3999, {"RAM":"64GB DDR5"}),
    ]
    output = ROOT / ".local/desktop-profile-preview.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="profile-preview-") as scratch:
        plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", Path(scratch), now=now)
        try:
            cards = []
            for index, (price, specs) in enumerate(examples):
                offer = Offer("example", str(index), "SIMULATED EXAMPLE — RTX 5080 gaming desktop",
                              "https://example.invalid/simulated", "Example seller", "new", specs,
                              price, 0, "in_stock", True, now.isoformat())
                candidate = plugin.prepare(offer_listing(offer))
                assessment = plugin.judge(candidate, plugin.read_history(candidate))
                cards.append(replace(plugin.card(assessment), title="SIMULATED — RTX 5080 prebuilt",
                                     badge="SIMULATED · " + plugin.card(assessment).badge))
            report = Report("Desktop alert preview", "Desktop alert preview — simulated examples",
                            "These demonstrate the new alert rules. They are not current listings or purchase recommendations.",
                            "No notifications sent. No live offer history or receipts changed.", tuple(cards))
            output.write_text(render_html(report), encoding="utf-8")
        finally:
            plugin.close()
    print(output)


if __name__ == "__main__":
    main()
