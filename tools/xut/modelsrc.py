# SPDX-License-Identifier: Apache-2.0
"""UNISIM model sources (spec §6.2 "Model identity").

A model source is one tree of UNISIM Verilog models: `unisims/`, `glbl.v` and optionally
`retarget/`. Its name is recorded in every result, so traces are only ever compared
like-for-like. `auto` prefers the Vivado install over the (older) GitHub submodule.
"""

from dataclasses import dataclass
from pathlib import Path

from xut.errors import ModelSourceError
from xut.paths import VIVADO_SRC, submodule_src


@dataclass(frozen=True)
class ModelSource:
    name: str  # "unisim-2025.2" | "unisim-gh-2020.1"
    src: Path  # holds unisims/, glbl.v and optionally retarget/

    @property
    def unisims(self) -> Path:
        return self.src / "unisims"

    @property
    def retarget(self) -> Path | None:
        r = self.src / "retarget"
        return r if r.is_dir() else None

    @property
    def glbl(self) -> Path:
        return self.src / "glbl.v"

    @property
    def search(self) -> list[Path]:
        """Library search directories (`-y`), UNISIM first."""
        return [self.unisims] + ([self.retarget] if self.retarget else [])


def _candidates() -> list[tuple[str, Path]]:
    """Every known model source, in `auto` preference order."""
    return [("unisim-2025.2", VIVADO_SRC), ("unisim-gh-2020.1", submodule_src())]


def known_model_sources() -> list[str]:
    """Every model source name xut knows, available on this machine or not."""
    return [n for n, _ in _candidates()]


def model_sources() -> dict[str, ModelSource]:
    """The model sources present on this machine, in preference order."""
    return {
        n: ModelSource(n, p)
        for n, p in _candidates()
        if (p / "unisims").is_dir() and (p / "glbl.v").is_file()
    }


def resolve(name: str = "auto") -> ModelSource:
    """The named model source, or the preferred available one for `auto`.

    Raises `ModelSourceError` (a `LookupError`) when it is not available."""
    have = model_sources()
    if name == "auto":
        if not have:
            raise ModelSourceError(
                "no UNISIM model source: install Vivado 2025.2 or init the submodule "
                "(git submodule update --init)"
            )
        return next(iter(have.values()))
    if name not in have:
        raise ModelSourceError(f"model source {name!r} unavailable (have: {sorted(have)})")
    return have[name]
