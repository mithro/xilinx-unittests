# SPDX-License-Identifier: Apache-2.0
"""A toy flip-flop for the hardware tests: fixtures/hw/TOYFF.v, with the step-2 toy's
catalog entry (``TOY_ENTRY``) and golden model (``ToyDff``): one definition of each."""

from pathlib import Path

from test_golden import ToyDff
from test_runner_base import TOY_ENTRY as TOY_HW_ENTRY

from xut.wrap import DutMap, DutSpec, build_map, spec_from_catalog

__all__ = ["TOYFF_V", "TOY_HW_ENTRY", "ToyDff", "toy_map", "toy_spec"]

FIX = Path(__file__).parent / "fixtures" / "hw"
TOYFF_V = FIX / "TOYFF.v"


def toy_spec(cfg: str, init: int) -> DutSpec:
    return spec_from_catalog(TOY_HW_ENTRY, cfg, {"INIT": f"1'b{init}"})


def toy_map(cfg: str, init: int) -> DutMap:
    return build_map(toy_spec(cfg, init))
