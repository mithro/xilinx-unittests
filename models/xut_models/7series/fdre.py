# SPDX-License-Identifier: Apache-2.0
"""FDRE golden model: UG953 v2026.1 pp. 375-376 (clean-room)."""

from ._common.flops import SdrFlop


class FDRE(SdrFlop):
    PRIM = "FDRE"
    CTRL = "R"  # synchronous reset: Q goes Low at the next clock transition (p375)
    CTRL_VALUE = 0
    CTRL_ASYNC = False
    INIT_DEFAULT = 0  # attribute table, p376
    PAGE = 375
    ATTR_PAGE = 376


MODEL = FDRE
