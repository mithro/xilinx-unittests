# SPDX-License-Identifier: Apache-2.0
"""Work-unit ownership map (docs/work-units.yaml, spec §13.1).

Loads the family's work units and derives the glob patterns each unit owns,
so `xut lint --branch` can refuse a branch that touches paths outside its
unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

#: A generated catalog file's basename (before `.yaml`) is exactly a
#: primitive name: uppercase letters, digits and `_` only, never a `.`.
#: `<PRIM>.overrides.yaml` is a work unit's, never infra's, but a naive
#: `catalog/7series/*.yaml` glob also matches it, because fnmatch's `*`
#: matches `.` too. Matching the primitive-name charset one character at a
#: time (no `*`) excludes any name containing a `.` or a lowercase letter,
#: which rules out `*.overrides.yaml` for every length up to the bound
#: below (27 is the longest current 7-series name).
_MAX_PRIM_NAME_LEN = 40
_PRIM_NAME_CHAR = "[A-Z0-9_]"

#: Paths that belong to no work unit: shared tooling, generated catalog
#: entries, docs infra, etc. (spec §10). A static constant, independent of
#: any particular `docs/work-units.yaml`.
INFRA_PATHS: list[str] = [
    "tools/**",
    "hw/**",
    "containers/**",
    ".github/**",
    "third_party/**",
    *(f"catalog/7series/{_PRIM_NAME_CHAR * n}.yaml" for n in range(1, _MAX_PRIM_NAME_LEN + 1)),
    "docs/work-units.yaml",
    "docs/review/**",
    "docs/templates/**",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "pyproject.toml",
]


@dataclass(frozen=True)
class WorkUnit:
    name: str
    family: str
    primitives: tuple[str, ...]
    group_dirs: tuple[str, ...]


def load_units(root: Path) -> dict[str, WorkUnit]:
    """Load `docs/work-units.yaml` from `root` into a name -> WorkUnit map.

    Raises ValueError naming any primitive listed in more than one unit.
    """
    data = yaml.safe_load((root / "docs/work-units.yaml").read_text())
    family = data["family"]
    seen: dict[str, str] = {}
    units: dict[str, WorkUnit] = {}
    for name, spec in data["units"].items():
        primitives = tuple(spec["primitives"])
        for prim in primitives:
            if prim in seen:
                raise ValueError(f"primitive {prim} listed in both {seen[prim]!r} and {name!r}")
            seen[prim] = name
        units[name] = WorkUnit(
            name=name,
            family=family,
            primitives=primitives,
            group_dirs=(spec["group"],),
        )
    return units


def owned_paths(unit: WorkUnit) -> list[str]:
    """Glob patterns for every path `unit` owns (spec §10, §13.1).

    Per-primitive paths (tests, overrides, per-prim model, status, findings)
    plus per-unit paths (the shared family model, unit progress logs).
    Generated files (`catalog/<family>/<PRIM>.yaml`) are infra-owned, never
    a work unit's.
    """
    family = unit.family
    group = unit.group_dirs[0]
    paths: list[str] = []
    for prim in unit.primitives:
        paths.append(f"tests/{family}/{group}/{prim}/**")
        paths.append(f"catalog/{family}/{prim}.overrides.yaml")
        paths.append(f"models/xut_models/{family}/{prim.lower()}.py")
        paths.append(f"status/{family}/{prim}.yaml")
        paths.append(f"findings/{prim}-*.md")
    paths.append(f"models/xut_models/{family}/_common/{unit.name}.py")
    paths.append(f"log/*-unit-{family}-{unit.name}-*.md")
    return paths


_UNIT_BRANCH = re.compile(r"^unit/[^/]+/(?P<unit>[^/]+)$")


def unit_for_branch(branch: str) -> str | None:
    """Return the work-unit name for a `unit/<family>/<unit>` branch, else None."""
    m = _UNIT_BRANCH.match(branch)
    return m.group("unit") if m else None


def branch_slug(branch: str) -> str:
    """Return `branch` with every `/` replaced by `-` (AGENTS.md §2, §6).

    Used to name a branch's own log entries:
    `log/<YYYY-MM-DDTHHMM>-<branch_slug(branch)>-<slug>.md`.
    """
    return branch.replace("/", "-")
