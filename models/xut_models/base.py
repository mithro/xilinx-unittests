# SPDX-License-Identifier: Apache-2.0
"""Golden-model base API (spec §3, §4.3). Standard library only.

A model is written clean-room from the libraries guide. Every output it
reports carries provenance: ``doc:<page>`` when the guide states the behaviour,
``inferred:<reason>`` when it had to be inferred. Provenance is one tag for the whole
output, or a tuple of per-bit tags (LSB = 0) when bits have different sources.

A bit may be reported as ``-`` (don't care: masked in every comparison) only where the
guide DECLARES it undefined, so its provenance must be ``doc:<page>`` (spec §5.3,
ruling S14); ``Out`` refuses a ``-`` bit with an ``inferred:`` tag. Where the guide is
silent, the model gives a definite ``inferred:`` value instead: a disagreement then
becomes a ``doc-gap`` finding in crosscheck, never a mask.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

# Whitespace, '#', '|', '=' would break .xtr lines; ',' separates per-bit tags there.
_PROV = re.compile(r"^(doc:\d+|inferred:[^\s#|=,]+)$")
_LIT = re.compile(r"^\s*\d*\s*'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_]+)\s*$")


class ModelUnsupported(Exception):
    """The stimulus needs behaviour this model does not describe (x inputs, GTS, ...)."""


class ModelContractError(ValueError):
    """A golden model broke the model API's contract (an output's bits or provenance,
    its declared ports): a model bug, never a test result."""


@dataclass(frozen=True)
class Out:
    bits: str  # MSB-first "0" / "1" / "-"
    # "doc:<page>" | "inferred:<reason>" for every bit, or one such tag per bit, LSB = 0
    prov: str | tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.bits or set(self.bits) - set("01-"):
            raise ModelContractError(f"model output bits must be 0/1/-: {self.bits!r}")
        if isinstance(self.prov, tuple):
            if len(self.prov) != len(self.bits):
                raise ModelContractError(
                    f"per-bit provenance has {len(self.prov)} tags for {len(self.bits)} bits"
                )
            tags = self.prov
        elif isinstance(self.prov, str):
            tags = (self.prov,)
        else:
            raise ModelContractError(f"provenance must be a str or a tuple of str: {self.prov!r}")
        for tag in tags:
            if not isinstance(tag, str) or not _PROV.match(tag):
                raise ModelContractError(
                    f"provenance must be doc:<page> or inferred:<reason>: {tag!r}"
                )
        for bit, ch in enumerate(reversed(self.bits)):  # LSB = 0, like per-bit tags
            tag = tags[bit] if len(tags) > 1 else tags[0]
            if ch == "-" and not tag.startswith("doc:"):
                raise ModelContractError(
                    f"bit {bit} is a don't-care ('-') with provenance {tag!r}: a bit may be "
                    "masked only where the documentation declares it undefined (doc:<page>, "
                    "spec §5.3); where the docs are silent give a definite inferred value"
                )


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
    def set_input(self, port: str, value: int) -> None:
        """A changed input. Ports changed at one time step arrive together (one call
        each, map order) before any edge or sample, so this must not depend on order."""

    @abstractmethod
    def clock_edge(self, port: str, rising: bool) -> None: ...

    def glbl(self, signal: str, value: int) -> None:
        raise ModelUnsupported(f"{self.PRIM}: glbl {signal} is not modelled")

    @abstractmethod
    def outputs(self) -> dict[str, Out]: ...
