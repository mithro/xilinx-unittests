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

from xut.errors import ConfigError


@dataclass(frozen=True)
class WorkUnit:
    name: str
    family: str
    primitives: tuple[str, ...]
    group_dirs: tuple[str, ...]


def _load(root: Path) -> dict:
    return yaml.safe_load((Path(root) / "docs/work-units.yaml").read_text())


def load_family(root: Path) -> str:
    """The device family name from `docs/work-units.yaml` — the single
    source of truth for the family name; no module hard-codes it."""
    return _load(root)["family"]


def load_units(root: Path) -> dict[str, WorkUnit]:
    """Load `docs/work-units.yaml` from `root` into a name -> WorkUnit map.

    Raises `ConfigError` (a ValueError) naming any primitive listed in more than one unit.
    """
    data = _load(root)
    family = data["family"]
    seen: dict[str, str] = {}
    units: dict[str, WorkUnit] = {}
    for name, spec in data["units"].items():
        primitives = tuple(spec["primitives"])
        for prim in primitives:
            if prim in seen:
                raise ConfigError(f"primitive {prim} listed in both {seen[prim]!r} and {name!r}")
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
    plus per-unit paths (the shared family model, the unit's shared test code under
    `tests/<family>/<group>/_shared/<unit>/`, unit progress logs).
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
    paths.append(f"tests/{family}/{group}/_shared/{unit.name}/**")
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
