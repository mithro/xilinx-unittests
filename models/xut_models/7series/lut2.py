# SPDX-License-Identifier: Apache-2.0
"""LUT2 golden model: UG953 v2026.1 pp. 491-492 (clean-room)."""

from ._common.luts import Lut


class LUT2(Lut):
    PRIM = "LUT2"
    N = 2
    INTRO_PAGE = 491  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 492  # Logic Table


MODEL = LUT2
