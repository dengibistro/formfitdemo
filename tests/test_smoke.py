"""Runs every module's built-in `if __name__ == "__main__":` smoke test, so
`pytest` covers them without converting each one by hand.

Excluded: machines/ai_narration*.py — they make real LLM + Supabase calls.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PYTHON_MODULES = [
    "biomechanics",
    "safety",
    "models",
    "machines.chest_press",
    "machines.shoulder_press",
    "machines.pec_deck",
    "machines.lat_pulldown",
    "machines.seated_row",
    "machines.leg_extension",
    "machines.leg_curl",
    "machines.leg_press",
    "machines.explanations",
]

SCAN_MODULES = ["measurements.mjs", "quality_gates.mjs", "capture_flow.mjs"]


@pytest.mark.parametrize("module", PYTHON_MODULES)
def test_python_smoke(module):
    result = subprocess.run([sys.executable, "-m", module], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", SCAN_MODULES)
def test_scan_smoke(name):
    result = subprocess.run(["node", str(ROOT / "scan" / name)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
