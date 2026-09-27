# SPDX-License-Identifier: Apache-2.0
"""LUT5 golden model: UG953 v2026.1 pp. 500-502 (clean-room)."""

from ._common.luts import Lut


class LUT5(Lut):
    PRIM = "LUT5"
    N = 5
    INTRO_PAGE = 500  # "By default, this value is zero ... (acting as a ground)"
    TABLE_PAGE = 501  # Logic Table


MODEL = LUT5
