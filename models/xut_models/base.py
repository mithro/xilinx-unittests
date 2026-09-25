# SPDX-License-Identifier: Apache-2.0
"""Golden-model base API (spec §3, §4.3). Standard library only.

A model is written clean-room from the libraries guide. Every output it
reports carries provenance: ``doc:<page>`` when the guide states the behaviour,
``inferred:<reason>`` when it had to be inferred. A bit the guide leaves
undefined is reported as ``-`` (don't care).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

_PROV = re.compile(r"^(doc:\d+|inferred:[^#|=]+)$")  # '#', '|', '=' would break .xtr lines
_LIT = re.compile(r"^\s*\d*\s*'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)\s*$")


class ModelUnsupported(Exception):
    """The stimulus needs behaviour this model does not describe (x inputs, GTS, ...)."""


@dataclass(frozen=True)
class Out:
    bits: str  # MSB-first "0" / "1" / "-"
    prov: str  # "doc:<page>" | "inferred:<reason>"

    def __post_init__(self) -> None:
        if not self.bits or set(self.bits) - set("01-"):
            raise ValueError(f"model output bits must be 0/1/-: {self.bits!r}")
        if not _PROV.match(self.prov):
            raise ValueError(f"provenance must be doc:<page> or inferred:<reason>: {self.prov!r}")


def bit_attr(v: str | int) -> int:
    """``1'b1``, ``"1'b0"``, ``1`` or ``"1"`` -> int."""
    if isinstance(v, int):
        return v
    m = _LIT.match(str(v))
    if m:
        radix = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(1).lower()]
        return int(m.group(2).replace("_", ""), radix)
    return int(str(v))


class Model(ABC):
    PRIM: ClassVar[str]
    FAMILY: ClassVar[str] = "7series"
    CLOCKS: ClassVar[tuple[str, ...]] = ()
    OUTPUTS: ClassVar[dict[str, int]] = {}

    def __init__(self, attrs: Mapping[str, str | int]) -> None:
        self.attrs = dict(attrs)
        self.claims_hit: set[str] = set()

    @classmethod
    @abstractmethod
    def inputs(cls) -> dict[str, int]:
        """Input port -> width (clock ports included)."""

    def hit(self, claim_id: str) -> None:
        self.claims_hit.add(claim_id)

    @abstractmethod
    def power_on(self) -> None:
        """State at time 0: glbl GSR is asserted until ROC_WIDTH."""

    @abstractmethod
    def set_input(self, port: str, value: int) -> None: ...

    @abstractmethod
    def clock_edge(self, port: str, rising: bool) -> None: ...

    def glbl(self, signal: str, value: int) -> None:
        raise ModelUnsupported(f"{self.PRIM}: glbl {signal} is not modelled")

    @abstractmethod
    def outputs(self) -> dict[str, Out]: ...
