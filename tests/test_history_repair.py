import json
from pathlib import Path

import pytest

from dealcore.locking import WriterLock
from scripts.repair_hardware_history import AUDITED, LEGACY, main, plan, repair


def observation(key, price=1000.0, bucket="used"):
    return dict(zip(("source", "listing_id", "part_key", "title"), key),
                bucket=bucket, unit_price=price, quantity=1, sold=0,
                first_seen="2026-08-08T16:12:29+00:00", last_seen="2026-10-05T01:57:45+00:00")


def history_path(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "state/hardware/US/prices.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def test_all_price_variants_removed_and_conditions_corrected_without_losing_evidence():
    rows = [observation(key) for key in AUDITED]
    rows.append(observation(next(iter(AUDITED)), price=9250))
    untouched = {**rows[0], "listing_id": "another-listing", "bucket": "new"}
    text = "".join(json.dumps(row) + "\n" for row in [*rows, untouched])
    result = plan(text)
    assert len(result.removed) == 5
    assert len(result.moved) == 2
    corrected = [json.loads(line) for line in result.text.splitlines()]
    assert corrected == [{**rows[4], "bucket": "new"}, {**rows[5], "bucket": "refurb"}, untouched]
    assert not plan(result.text).changed
    assert plan(result.text).text == result.text


@pytest.mark.parametrize("field,value", [("source", "manual"), ("part_key", "a100_80"),
                                        ("title", "New unrelated listing")])
def test_reused_listing_ids_and_different_sources_are_preserved(field, value):
    row = {**observation(next(iter(AUDITED))), field: value}
    text = json.dumps(row) + "\r\n"
    assert plan(text).text == text
    assert not plan(text).changed


def test_dry_run_leaves_original_and_directory_untouched(tmp_path):
    text = json.dumps(observation(next(iter(AUDITED)))) + "\n"
    path = history_path(tmp_path, text)
    before = list(tmp_path.rglob("*"))
    assert repair(path).changed
    assert path.read_bytes() == text.encode()
    assert list(tmp_path.rglob("*")) == before


def test_apply_creates_exact_backup_and_preserves_receipts(tmp_path):
    text = json.dumps(observation(next(iter(AUDITED)))) + "\n"
    path = history_path(tmp_path, text)
    receipts = path.with_name("alerts.json")
    receipts.write_bytes(b'{"existing": "receipt"}')
    backup = tmp_path / "before.jsonl"
    assert repair(path, backup=backup).changed
    assert backup.read_bytes() == text.encode()
    assert path.read_bytes() == b""
    assert receipts.read_bytes() == b'{"existing": "receipt"}'
    assert not repair(path, backup=backup).changed


def test_active_writer_prevents_backup_and_repair(tmp_path):
    text = json.dumps(observation(next(iter(AUDITED)))) + "\n"
    path = history_path(tmp_path, text)
    backup = tmp_path / "before.jsonl"
    with WriterLock(path.parent.parent / ".writer.lock"):
        with pytest.raises(ValueError, match="Another hardware state writer"):
            repair(path, backup=backup)
    assert not backup.exists()
    assert path.read_bytes() == text.encode()


@pytest.mark.parametrize("bad_line", ["{broken", "[]"])
def test_corrupt_history_aborts_before_backup_or_replacement(tmp_path, bad_line):
    text = json.dumps(observation(next(iter(AUDITED)))) + "\n" + bad_line
    path = history_path(tmp_path, text)
    backup = tmp_path / "before.jsonl"
    with pytest.raises(ValueError):
        repair(path, backup=backup)
    assert not backup.exists()
    assert path.read_bytes() == text.encode()


def test_existing_backup_is_never_overwritten(tmp_path):
    text = json.dumps(observation(next(iter(AUDITED)))) + "\n"
    path = history_path(tmp_path, text)
    backup = tmp_path / "before.jsonl"
    backup.write_bytes(b"earlier backup")
    with pytest.raises(FileExistsError):
        repair(path, backup=backup)
    assert path.read_bytes() == text.encode()
    assert backup.read_bytes() == b"earlier backup"


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_apply_preserves_unaffected_bytes_and_line_endings(tmp_path, ending):
    removed = observation(next(iter(AUDITED)))
    untouched = {**removed, "listing_id": "unrelated"}
    kept = json.dumps(untouched, indent=None) + ending
    path = history_path(tmp_path, json.dumps(removed) + ending + kept)
    repair(path, backup=tmp_path / "before.jsonl")
    assert path.read_bytes() == kept.encode()


def test_cli_requires_apply_and_backup_together(tmp_path):
    path = history_path(tmp_path, "")
    with pytest.raises(SystemExit) as exc:
        main([str(path), "--apply"])
    assert exc.value.code == 2


@pytest.mark.parametrize("key,part", LEGACY.items())
def test_legacy_corrections_agree_with_the_parser_and_preserve_price_evidence(key, part):
    from alerters.hardware.native.match import match
    parsed = match(key[3], price=5000)
    if part is None:
        assert parsed.junk or parsed.is_system
    else:
        assert parsed.part.key == part and not parsed.is_system and not parsed.junk
    rows = [observation(key, price=price) for price in (5000, 5500)]
    result = plan("".join(json.dumps(row) + "\n" for row in rows))
    if part is None:
        assert result.text == "" and len(result.removed) == 2
    else:
        corrected = [json.loads(line) for line in result.text.splitlines()]
        assert corrected == [{**row, "part_key": part} for row in rows]
        assert len(result.moved) == 2
        assert not plan(result.text).changed


def test_unlabelled_and_repurposed_legacy_rows_are_preserved():
    key = next(iter(LEGACY))
    rows = [{**observation(key), "title": ""},
            {**observation(key), "title": "A newly repurposed listing"},
            {**observation(key), "source": "manual"},
            {**observation(key), "title": []}]
    text = "".join(json.dumps(row) + "\n" for row in rows)
    assert plan(text).text == text
    assert not plan(text).changed


def test_quarantine_is_optional_and_preserves_all_original_evidence(tmp_path):
    unknown = {**observation(next(iter(AUDITED))), "title": ""}
    valid = {**unknown, "listing_id": "verified", "title": "RTX 3090 graphics card"}
    text = "".join(json.dumps(row) + "\n" for row in (unknown, valid))
    path = history_path(tmp_path, text)
    assert not repair(path).changed
    result = repair(path, backup=tmp_path / "before.jsonl", quarantine_unlabelled=True)
    assert result.quarantined == (unknown,)
    archive = path.with_name("prices-unaudited.jsonl")
    assert json.loads(archive.read_text()) == unknown
    assert json.loads(path.read_text()) == valid
    assert not repair(path, backup=tmp_path / "before.jsonl", quarantine_unlabelled=True).changed


def test_archive_is_written_before_active_history_and_retry_does_not_duplicate(tmp_path, monkeypatch):
    from scripts import repair_hardware_history as module
    unknown = {**observation(next(iter(AUDITED))), "title": ""}
    text = json.dumps(unknown) + "\n"
    path = history_path(tmp_path, text)
    original = module.atomic_bytes
    def crash(target, data):
        if target == path:
            raise OSError("simulated interruption")
        original(target, data)
    monkeypatch.setattr(module, "atomic_bytes", crash)
    with pytest.raises(OSError):
        repair(path, backup=tmp_path / "first.jsonl", quarantine_unlabelled=True)
    assert path.read_text() == text
    archive = path.with_name("prices-unaudited.jsonl")
    assert json.loads(archive.read_text()) == unknown
    monkeypatch.setattr(module, "atomic_bytes", original)
    repair(path, backup=tmp_path / "second.jsonl", quarantine_unlabelled=True)
    assert path.read_bytes() == b""
    assert len(archive.read_text().splitlines()) == 1


def test_corrupt_archive_aborts_without_mutating_either_file(tmp_path):
    unknown = {**observation(next(iter(AUDITED))), "title": ""}
    text = json.dumps(unknown) + "\n"
    path = history_path(tmp_path, text)
    archive = path.with_name("prices-unaudited.jsonl")
    archive.write_bytes(b"broken")
    backup = tmp_path / "before.jsonl"
    with pytest.raises(ValueError):
        repair(path, backup=backup, quarantine_unlabelled=True)
    assert path.read_text() == text
    assert archive.read_bytes() == b"broken" and not backup.exists()
