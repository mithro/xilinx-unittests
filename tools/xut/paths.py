# SPDX-License-Identifier: Apache-2.0
"""Repository path discovery."""

from pathlib import Path

_MARKER = 'name = "xilinx-unittests"'


def repo_root(start: Path | None = None) -> Path:
    """Return the repository root (directory holding our pyproject.toml)."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        pp = d / "pyproject.toml"
        if pp.is_file() and _MARKER in pp.read_text():
            return d
    raise FileNotFoundError(f"not inside xilinx-unittests (searched up from {here})")


def cache_dir() -> Path:
    return repo_root() / ".cache"


VIVADO_UNISIM = Path("/opt/xilinx/Vivado/2025.2/data/verilog/src/unisims")
VIVADO_RETARGET = Path("/opt/xilinx/Vivado/2025.2/data/verilog/src/retarget")


def submodule_unisim() -> Path:
    return repo_root() / "third_party/XilinxUnisimLibrary/verilog/src/unisims"
