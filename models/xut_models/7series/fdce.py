# SPDX-License-Identifier: Apache-2.0
"""FDCE golden model: UG953 v2026.1 pp. 369-370 (clean-room)."""

from ._common.flops import SdrFlop


class FDCE(SdrFlop):
    PRIM = "FDCE"
    CTRL = "CLR"  # asynchronous clear: overrides all inputs, Q Low (p369)
    CTRL_VALUE = 0
    CTRL_ASYNC = True
    INIT_DEFAULT = 0  # attribute table, p370
    PAGE = 369
    ATTR_PAGE = 370


MODEL = FDCE
