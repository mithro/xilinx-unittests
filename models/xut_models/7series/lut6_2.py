# SPDX-License-Identifier: Apache-2.0
"""LUT6_2 golden model: UG953 v2026.1 pp. 509-512 (clean-room)."""

from ._common.luts import DualLut


class LUT6_2(DualLut):  # noqa: N801 - the primitive's own name
    PRIM = "LUT6_2"
    INTRO_PAGE = 509  # the zero default, the lower half feeding O5, the OR example
    TABLE_PAGE = 510  # Logic Table (pp. 510-511)


MODEL = LUT6_2
