# SPDX-License-Identifier: Apache-2.0
"""Find the golden model for a primitive: module xut_models.<family>.<prim lower>, attr MODEL."""

import importlib

from xut_models.base import Model


def get(family: str, prim: str) -> type[Model]:
    """The ``MODEL`` class of ``xut_models.<family>.<prim lower>``; LookupError if none."""
    name = f"xut_models.{family}.{prim.lower()}"
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        # Only the model module (or its family package) being absent means "no model"; a
        # missing import *inside* an existing model is a bug and must stay loud.
        if e.name not in (name, f"xut_models.{family}"):
            raise
        raise LookupError(f"no golden model for {family}/{prim}") from e
    model = getattr(mod, "MODEL", None)
    if not (isinstance(model, type) and issubclass(model, Model) and prim == model.PRIM):
        raise LookupError(f"xut_models.{family}.{prim.lower()}.MODEL is not a {prim} Model")
    return model
