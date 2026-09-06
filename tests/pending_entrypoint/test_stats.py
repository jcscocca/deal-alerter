"""--stats has to report each condition bucket exactly once.

History.stats() takes a *condition* and re-maps it through bucket_for(), so
iterating over bucket names instead silently aliases "refurb" onto the default
and prints the used bucket twice -- while never showing refurb at all. That
matters beyond cosmetics: the roadmap reads these medians against catalog
reference prices to decide when to retune them, and Apple Certified Refurbished
is one of the sources feeding the log.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.history import History
from check_deals import show_stats


@pytest.fixture
def history(tmp_path):
    store = History(tmp_path / "prices.db")
    yield store
    store.close()


def _rows(captured: str) -> list[str]:
    """The data lines, skipping the count line, header and rule."""
    return [
        line
        for line in captured.splitlines()
        if line.startswith("RTX 3090")
    ]


class TestStatsBuckets:
    def test_each_observation_is_reported_once(
        self, history: History, capsys
    ) -> None:
        history.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=900.0,
            source="ebay",
            listing_id="used-1",
        )
        history.commit()

        show_stats(history)
        rows = _rows(capsys.readouterr().out)

        assert len(rows) == 1, f"one observation, one row; got {rows}"
        assert "used" in rows[0]

    def test_refurb_is_reported_as_refurb(self, history: History, capsys) -> None:
        history.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=900.0,
            source="ebay",
            listing_id="used-1",
        )
        history.record(
            part_key="rtx_3090",
            condition="refurbished",
            unit_price=1100.0,
            source="ebay",
            listing_id="refurb-1",
        )
        history.commit()

        show_stats(history)
        rows = _rows(capsys.readouterr().out)

        assert len(rows) == 2
        refurb = [line for line in rows if "refurb" in line]
        assert len(refurb) == 1
        assert "$1,100" in refurb[0], "refurb row must show refurb prices"
