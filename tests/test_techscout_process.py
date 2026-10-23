"""The Windows updater must prove backend identity before stopping a process."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("techscout_process", Path(__file__).resolve().parents[1] / "scripts/windows/techscout_process.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
APP = r"C:\ProgramData\DealAlerter\app"
LOCAL = r"C:\Users\shopper\AppData\Local\TechScout"
PYTHON = LOCAL + r"\venv\Scripts\pythonw.exe"
ARGV = [PYTHON, "-m", "alerters.techscout", "--serve", "--settings", LOCAL + r"\settings.json", "--output", LOCAL + r"\reports"]


def test_scoped_backend_requires_actual_app_cwd_and_matching_per_user_environment():
    result = MODULE.classify_process(ARGV, PYTHON, APP, APP)
    assert result["recognized"] and result["data_directory"] == LOCAL
    assert result["is_techscout"] and result["app_scope"]


@pytest.mark.parametrize("argv,exe,cwd", [
    ([PYTHON, "-m", "http.server", "8768"], PYTHON, APP),
    ([PYTHON, "-m", "alerters.techscout", "--query", "--serve"], PYTHON, APP),
    (ARGV, r"C:\Python313\python.exe", APP),
    (ARGV, PYTHON, r"C:\Users\shopper\unrelated-app"),
    (ARGV[:-2] + ["--output", r"C:\other\reports"], PYTHON, APP),
    (ARGV + ["--settings", LOCAL + r"\settings.json"], PYTHON, APP),
    ([PYTHON, "-m", "alerters.techscout", "--serve"], PYTHON, APP),
])
def test_port_or_module_name_alone_cannot_authorize_process_stop(argv, exe, cwd):
    assert not MODULE.classify_process(argv, exe, cwd, APP)["recognized"]


def test_windows_path_comparison_supports_case_variations_and_explicit_equals_options():
    argv = ARGV[:4] + ["--settings=" + LOCAL + r"\settings.json", "--output=" + LOCAL + r"\reports"]
    assert MODULE.classify_process(argv, PYTHON.upper(), APP.upper(), APP)["recognized"]


def test_venv_base_child_requires_same_scoped_wrapper_and_pyvenv_base_identity():
    base = r"C:\Users\shopper\AppData\Local\Programs\Python\Python311\pythonw.exe"
    parent = {**MODULE.classify_process(ARGV, PYTHON, APP, APP), "pid": 123}
    child = MODULE.classify_process(ARGV, base, APP, APP, base_executable=base, parent=parent)
    assert child["recognized"] and child["venv_wrapper_pid"] == 123
    assert not MODULE.classify_process(ARGV, base, APP, APP, base_executable=base)["recognized"]
    assert not MODULE.classify_process(ARGV, base, APP, APP, base_executable=r"C:\other\pythonw.exe", parent=parent)["recognized"]
    assert not MODULE.classify_process(ARGV, base, APP, APP, base_executable=base, parent={**parent,"data_directory":r"C:\other"})["recognized"]
