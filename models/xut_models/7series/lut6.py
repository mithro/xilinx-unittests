# SPDX-License-Identifier: Apache-2.0
"""LUT6 golden model: UG953 v2026.1 pp. 504-507 (clean-room)."""

from ._common.luts import Lut


class LUT6(Lut):
    PRIM = "LUT6"
    N = 6
    INTRO_PAGE = 504  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 504  # Logic Table


MODEL = LUT6
