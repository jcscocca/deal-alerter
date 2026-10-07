"""Run the browser's pure selection rules without a browser or network."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_browsing_rules():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser rule tests require Node")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "--test", str(root / "tests/techscout_browsing.test.cjs")],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
