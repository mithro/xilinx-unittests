# SPDX-License-Identifier: Apache-2.0
"""JSON schemas for catalog entries, status files and test.yaml (spec §4, §11).

`load_schema(name)` reads `<name>.schema.json` from this directory once and caches it;
`validate(obj, name)` is the one validation entry point every module uses.
"""

import json
from functools import cache
from pathlib import Path

import jsonschema

SCHEMA_DIR = Path(__file__).resolve().parent


@cache
def load_schema(name: str) -> dict:
    """The parsed `<name>.schema.json` (`catalog`, `status` or `test`), cached."""
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())


def validate(obj: object, name: str) -> None:
    """Raise `jsonschema.ValidationError` if `obj` does not match schema `name`."""
    jsonschema.validate(obj, load_schema(name))
