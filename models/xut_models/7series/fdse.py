# SPDX-License-Identifier: Apache-2.0
"""FDSE golden model: UG953 v2026.1 pp. 378-379 (clean-room)."""

from ._common.flops import SdrFlop


class FDSE(SdrFlop):
    PRIM = "FDSE"
    CTRL = "S"  # synchronous set: Q goes High at the next clock transition (p378)
    CTRL_VALUE = 1
    CTRL_ASYNC = False
    INIT_DEFAULT = 1  # attribute table, p379
    PAGE = 378
    ATTR_PAGE = 379


MODEL = FDSE
