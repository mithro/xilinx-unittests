# SPDX-License-Identifier: Apache-2.0
"""LUT1 golden model: UG953 v2026.1 pp. 488-489 (clean-room)."""

from ._common.luts import Lut


class LUT1(Lut):
    PRIM = "LUT1"
    N = 1
    INTRO_PAGE = 488  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 489  # Logic Table


MODEL = LUT1
