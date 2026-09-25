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

#: Paths that belong to no work unit: shared tooling, generated catalog
#: entries, docs infra, etc. (spec §10). Populated by `load_units`.
INFRA_PATHS: list[str] = [
    "tools/**",
    "hw/**",
    "containers/**",
    ".github/**",
    "third_party/**",
    "catalog/7series/*.yaml",
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
