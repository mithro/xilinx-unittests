# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.paths: one Vivado root, every Vivado path derived from it."""

from pathlib import Path

from xut import doctor, paths


def test_single_vivado_root():
    assert Path("/opt/xilinx/Vivado/2025.2") == paths.VIVADO_ROOT
    assert paths.VIVADO_UNISIM == paths.VIVADO_ROOT / "data/verilog/src/unisims"
    assert paths.VIVADO_RETARGET == paths.VIVADO_ROOT / "data/verilog/src/retarget"
    assert paths.VIVADO_SETTINGS == paths.VIVADO_ROOT / "settings64.sh"


def test_doctor_uses_paths_vivado_settings():
    assert doctor.VIVADO_SETTINGS is paths.VIVADO_SETTINGS


def test_vivado_root_literal_defined_once():
    """The version-specific root string appears in exactly one tools/xut module."""
    xut_dir = Path(paths.__file__).resolve().parent
    hits = [f for f in xut_dir.rglob("*.py") if "/opt/xilinx" in f.read_text()]
    assert hits == [xut_dir / "paths.py"]
    assert (xut_dir / "paths.py").read_text().count("/opt/xilinx") == 1
