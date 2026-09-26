# SPDX-License-Identifier: Apache-2.0
"""FDPE golden model: UG953 v2026.1 pp. 372-373 (clean-room)."""

from ._common.flops import SdrFlop


class FDPE(SdrFlop):
    PRIM = "FDPE"
    CTRL = "PRE"  # asynchronous preset: overrides all inputs, Q High (p372)
    CTRL_VALUE = 1
    CTRL_ASYNC = True
    INIT_DEFAULT = 1  # attribute table, p373
    PAGE = 372
    ATTR_PAGE = 373


MODEL = FDPE
