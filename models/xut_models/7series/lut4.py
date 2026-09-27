# SPDX-License-Identifier: Apache-2.0
"""LUT4 golden model: UG953 v2026.1 pp. 497-499 (clean-room)."""

from ._common.luts import Lut


class LUT4(Lut):
    PRIM = "LUT4"
    N = 4
    INTRO_PAGE = 497  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 498  # Logic Table


MODEL = LUT4
