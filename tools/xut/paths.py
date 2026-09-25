# SPDX-License-Identifier: Apache-2.0
"""Repository path discovery."""

from pathlib import Path

from xut.errors import NotInRepoError

_MARKER = 'name = "xilinx-unittests"'


def repo_root(start: Path | None = None) -> Path:
    """Return the repository root (directory holding our pyproject.toml)."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        pp = d / "pyproject.toml"
        if pp.is_file() and _MARKER in pp.read_text():
            return d
    raise NotInRepoError(f"not inside xilinx-unittests (searched up from {here})")


def cache_dir() -> Path:
    return repo_root() / ".cache"


#: The one Vivado install this suite targets (global constraints). Every Vivado path
#: below is derived from it, so a version bump is a one-line change.
VIVADO_ROOT = Path("/opt/xilinx/Vivado/2025.2")
#: Verilog model tree: holds unisims/, retarget/ and glbl.v (model source `unisim-2025.2`).
VIVADO_SRC = VIVADO_ROOT / "data/verilog/src"
#: UNISIM simulation models (catalog source; CI falls back to `submodule_unisim()`).
VIVADO_UNISIM = VIVADO_SRC / "unisims"
#: Retarget-only models (BUFGCE_1, BUFGMUX*, ROM*X1, ...), never in `VIVADO_UNISIM`.
VIVADO_RETARGET = VIVADO_SRC / "retarget"
#: Settings script, only ever sourced in a subshell; its presence enables xsim/vivado.
VIVADO_SETTINGS = VIVADO_ROOT / "settings64.sh"


def submodule_src() -> Path:
    """The XilinxUnisimLibrary submodule's model tree (model source `unisim-gh-2020.1`)."""
    return repo_root() / "third_party/XilinxUnisimLibrary/verilog/src"


def submodule_unisim() -> Path:
    return submodule_src() / "unisims"
