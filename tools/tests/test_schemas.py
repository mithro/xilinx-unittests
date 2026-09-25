# SPDX-License-Identifier: Apache-2.0
"""Tests for xut.schemas: one cached loader + validator for every JSON schema."""

import jsonschema
import pytest

from xut import schemas, status
from xut.catalog import model


def test_load_schema_is_cached():
    a = schemas.load_schema("status")
    assert a is schemas.load_schema("status")
    assert a["type"] == "object"


@pytest.mark.parametrize("name", ["catalog", "status", "test"])
def test_every_schema_loads(name):
    assert "$schema" in schemas.load_schema(name)


def test_unknown_schema_name():
    with pytest.raises(FileNotFoundError):
        schemas.load_schema("nope")


def test_validate_raises_validation_error():
    with pytest.raises(jsonschema.ValidationError):
        schemas.validate({}, "test")


def test_modules_do_not_define_their_own_loader():
    """catalog.model and status delegate to xut.schemas (no private copies)."""
    for mod in (model, status):
        assert not hasattr(mod, "_schema")
        assert not hasattr(mod, "SCHEMA_PATH")
