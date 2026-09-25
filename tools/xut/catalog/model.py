# SPDX-License-Identifier: Apache-2.0
"""Catalog entries: generated ``<PRIM>.yaml`` with ``<PRIM>.overrides.yaml`` layered on."""

import copy
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

from xut import schemas
from xut.errors import OverrideError, OverrideTypeError


def is_enumerated(values: list[str]) -> bool:
    """True if an attribute's ``allowed`` values are a set of discrete literals, not a
    range such as ``1 to 128``, ``190-210`` or ``1'b0 to 1'b1``. Shared by
    ``xut.catalog.build`` (UG953 cross-check) and ``xut.status`` (coverage bins, spec
    §9): a non-enumerated or undeclared (``allowed`` is advisory and may be empty)
    attribute collapses to a single ``attr:<A>`` bin, an enumerated one to one
    ``attr:<A>=<v>`` bin per value."""
    return bool(values) and all(
        re.fullmatch(r"\"[^\"]*\"|[A-Za-z0-9_.']+", v) and not re.fullmatch(r"\d+-\d+", v)
        for v in values
    )


@dataclass
class CatalogEntry:
    name: str
    family: str
    group: str
    subgroup: str
    description: str
    doc: dict  # {guide, edition, page}
    model: dict  # {library, file}
    ports: list[dict] = field(default_factory=list)  # {name, direction, width, cls, doc_function}
    attributes: list[dict] = field(default_factory=list)  # {name, kind, width, default, ...}
    design_entry: dict = field(default_factory=dict)
    claims: list[dict] = field(default_factory=list)  # {id, text, page, provenance}
    status_undocumented: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def validate(data: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` is not a valid catalog entry."""
    schemas.validate(data, "catalog")


def _merge_named(items: list[dict], patch: dict, what: str, prim: str) -> list[dict]:
    by_name = {it["name"]: it for it in items}
    for name, upd in patch.items():
        if name not in by_name:
            raise OverrideError(f"{prim}.overrides.yaml: unknown {what} {name!r}")
        by_name[name].update(upd)
    return items


def merge(generated: dict, overrides: dict, prim: str = "?") -> dict:
    """Apply overrides: ports/attributes are dicts keyed by name updating matching
    entries, ``claims`` replaces the list, any other key replaces the value."""
    out = copy.deepcopy(generated)
    for key, val in (overrides or {}).items():
        if key in ("ports", "attributes"):
            if not isinstance(val, dict):
                raise OverrideTypeError(
                    f"{prim}.overrides.yaml: {key} must be a mapping keyed by name"
                )
            out[key] = _merge_named(out.get(key, []), val, key[:-1], prim)
        else:
            out[key] = copy.deepcopy(val)
    return out


def load_entry(family: str, name: str, root: Path) -> CatalogEntry:
    """Load ``<root>/catalog/<family>/<name>.yaml`` with its overrides merged and validated."""
    d = Path(root) / "catalog" / family
    data = yaml.safe_load((d / f"{name}.yaml").read_text())
    ov = d / f"{name}.overrides.yaml"
    if ov.is_file():
        data = merge(data, yaml.safe_load(ov.read_text()) or {}, name)
    validate(data)
    return CatalogEntry(**{f.name: data[f.name] for f in fields(CatalogEntry)})
