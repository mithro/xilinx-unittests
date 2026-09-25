# SPDX-License-Identifier: Apache-2.0
"""Per-primitive status (``status/<family>/<PRIM>.yaml``, spec §11).

The status file is the source of truth for a primitive's measured results and
functional-coverage bins. ``xut status generate`` (Task 7) renders it into
`status/PROGRESS.md` and friends; this module only defines the schema, loads
and validates a status file, and builds a fresh stub.
"""

import json
from pathlib import Path

import jsonschema
import yaml

from xut.catalog.model import CatalogEntry, is_enumerated

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "status.schema.json"

#: Valid values for a `results` entry (spec §11).
RESULT_VALUES = ("pass", "fail", "error", "skip", "not-run", "unsupported", "n/a")

HEADER = "# SPDX-License-Identifier: Apache-2.0\n"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(data: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` is not a valid status entry."""
    jsonschema.validate(data, _schema())


def load_status(path: Path) -> dict:
    """Load and validate a ``status/<family>/<PRIM>.yaml`` file."""
    data = yaml.safe_load(Path(path).read_text())
    validate(data)
    return data


def coverage_bins(entry: CatalogEntry) -> list[str]:
    """Functional coverage bins for `entry` (spec §9): ``port:<P>`` for every port,
    ``attr:<A>=<v>`` for every allowed enumerated value of an attribute, ``attr:<A>``
    for a non-enumerated or undeclared (``allowed`` is advisory and may be empty)
    attribute, and ``claim:<id>`` for every behavioural claim."""
    bins: list[str] = [f"port:{p['name']}" for p in entry.ports]
    for a in entry.attributes:
        allowed = a.get("allowed") or []
        if is_enumerated(allowed):
            bins.extend(f"attr:{a['name']}={v}" for v in allowed)
        else:
            bins.append(f"attr:{a['name']}")
    bins.extend(f"claim:{c['id']}" for c in entry.claims)
    return bins


def new_stub(entry: CatalogEntry, unit: str) -> dict:
    """A fresh status entry for `entry`, owned by work unit `unit`: no measurements or
    results yet, every coverage bin uncovered."""
    return {
        "primitive": entry.name,
        "family": entry.family,
        "work_unit": unit,
        "model_library": entry.model["library"],
        "measured": {"tree_hash": None, "tools": {}},
        "results": {},
        "findings": [],
        "coverage": {"covered": [], "uncovered": coverage_bins(entry)},
        "notes": "",
    }


def dump_stub(entry: CatalogEntry, unit: str) -> str:
    """Render ``new_stub(entry, unit)`` as deterministic YAML text with the SPDX header."""
    data = new_stub(entry, unit)
    validate(data)
    return HEADER + yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
