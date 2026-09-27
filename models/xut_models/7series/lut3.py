# SPDX-License-Identifier: Apache-2.0
"""LUT3 golden model: UG953 v2026.1 pp. 494-495 (clean-room)."""

from ._common.luts import Lut


class LUT3(Lut):
    PRIM = "LUT3"
    N = 3
    INTRO_PAGE = 494  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 495  # Logic Table


MODEL = LUT3
