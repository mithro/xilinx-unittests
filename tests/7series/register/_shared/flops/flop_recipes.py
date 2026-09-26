# SPDX-License-Identifier: Apache-2.0
"""Stimulus recipes shared by the flops work unit (FDRE, FDSE, FDCE, FDPE).

Task 20 needs only the ``FlopKind`` table the model tests key off; the
stimulus recipes themselves (``all_configs``, ``Flop``, ...) land in Task 21.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlopKind:
    prim: str
    ctrl: str  # R | S | CLR | PRE
    is_async: bool
    word: str  # reset | set | clear | preset (used in test ids)
    forced: int  # the value the control drives onto Q
    init_default: int


KINDS = {
    "FDRE": FlopKind("FDRE", "R", False, "reset", 0, 0),
    "FDSE": FlopKind("FDSE", "S", False, "set", 1, 1),
    "FDCE": FlopKind("FDCE", "CLR", True, "clear", 0, 0),
    "FDPE": FlopKind("FDPE", "PRE", True, "preset", 1, 1),
}
