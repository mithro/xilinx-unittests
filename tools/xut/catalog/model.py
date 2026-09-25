# SPDX-License-Identifier: Apache-2.0
"""Catalog entries: generated ``<PRIM>.yaml`` with ``<PRIM>.overrides.yaml`` layered on."""

import copy
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "catalog.schema.json"


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


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(data: dict) -> None:
    """Raise ``jsonschema.ValidationError`` if ``data`` is not a valid catalog entry."""
    jsonschema.validate(data, _schema())


def _merge_named(items: list[dict], patch: dict, what: str, prim: str) -> list[dict]:
    by_name = {it["name"]: it for it in items}
    for name, upd in patch.items():
        if name not in by_name:
            raise KeyError(f"{prim}.overrides.yaml: unknown {what} {name!r}")
        by_name[name].update(upd)
    return items


def merge(generated: dict, overrides: dict, prim: str = "?") -> dict:
    """Apply overrides: ports/attributes are dicts keyed by name updating matching
    entries, ``claims`` replaces the list, any other key replaces the value."""
    out = copy.deepcopy(generated)
    for key, val in (overrides or {}).items():
        if key in ("ports", "attributes"):
            if not isinstance(val, dict):
                raise TypeError(f"{prim}.overrides.yaml: {key} must be a mapping keyed by name")
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
