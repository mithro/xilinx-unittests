# SPDX-License-Identifier: Apache-2.0
"""Harness program images (spec §7.1): the operation words the stepped harness's
sequencer executes from its stimulus BRAM. Standard library only.

One 32-bit word per operation, op in [31:28]::

    0x1 SET     [27:16] chunk c, [15:0] data   in_nxt[16c+15:16c] = data
    0x2 COMMIT                                 the slot's in_vec = in_nxt; then MARGIN cycles
    0x3 EDGE    [12] level, [11:0] clock i     the slot's clock i = level; then MARGIN cycles
    0x4 WAIT    [27:0] n                       n + 1 more cycles
    0x5 SAMPLE                                 print "S <n> <out_vec>" (n counts from 0)
    0xF END

The harness, not the program, holds MARGIN system cycles after every COMMIT and EDGE:
an in_vec change, the next DUT clock edge and the next capture are always at least
MARGIN cycles apart, whatever the program says (correctness by construction). A slot's
in_vec powers up as its program's ``t0`` (the harness flip-flops' INIT, baked into the
bitstream), and its clocks power up low.
"""

from __future__ import annotations

from dataclasses import dataclass

OP_SET, OP_COMMIT, OP_EDGE, OP_WAIT, OP_SAMPLE, OP_END = 0x1, 0x2, 0x3, 0x4, 0x5, 0xF
CHUNK = 16
MAX_CHUNKS = 1 << 12
MAX_CLOCKS = 1 << 12
MAX_WAIT = (1 << 28) - 1
#: The harness's defaults (xut_hw_ctrl parameters). A bitstream reports its own in `I`.
MAXWORDS = 8192
MARGIN = 16


class HwImageError(ValueError):
    """An operation the harness cannot express, or a program too long for it."""


def width(n: int) -> int:
    """A wrapper vector's width: ``max(1, n)`` (spec §5.2 wrappers never have 0 bits)."""
    return max(1, n)


def chunks(bits: str) -> list[int]:
    """MSB-first ``bits`` as 16-bit chunks, chunk 0 = bits[15:0]."""
    lsb = bits[::-1]
    return [int(lsb[i : i + CHUNK][::-1], 2) for i in range(0, len(lsb), CHUNK)]


def w_set(chunk: int, data: int) -> int:
    if not (0 <= chunk < MAX_CHUNKS and 0 <= data < 1 << CHUNK):
        raise HwImageError(f"SET chunk={chunk} data={data:#x} does not fit")
    return (OP_SET << 28) | (chunk << 16) | data


def w_commit() -> int:
    return OP_COMMIT << 28


def w_edge(idx: int, level: int) -> int:
    if not (0 <= idx < MAX_CLOCKS and level in (0, 1)):
        raise HwImageError(f"EDGE clock={idx} level={level} does not fit")
    return (OP_EDGE << 28) | (level << 12) | idx


def w_wait(n: int) -> int:
    if not 0 <= n <= MAX_WAIT:
        raise HwImageError(f"WAIT {n} does not fit 28 bits")
    return (OP_WAIT << 28) | n


W_SAMPLE = OP_SAMPLE << 28
W_END = OP_END << 28


def decode(w: int) -> tuple[int, int, int]:
    """``(op, a, b)``: SET (chunk, data), EDGE (clock, level), WAIT (n, 0), else (0, 0)."""
    op = (w >> 28) & 0xF
    if op == OP_SET:
        return op, (w >> 16) & 0xFFF, w & 0xFFFF
    if op == OP_EDGE:
        return op, w & 0xFFF, (w >> 12) & 1
    if op == OP_WAIT:
        return op, w & MAX_WAIT, 0
    return op, 0, 0


@dataclass(frozen=True)
class HwProgram:
    nin: int
    nclk: int
    noutw: int  # max(1, nout): the width of every sample
    t0: str  # MSB-first width(nin) chars of 0/1: the slot's power-on in_vec
    words: tuple[int, ...]
    labels: tuple[str, ...]  # sample labels, in sample order


def _check_bits(bits: str, n: int, what: str) -> None:
    if len(bits) != n:
        raise HwImageError(f"{what} {bits!r} is not {n} char(s)")
    if set(bits) - {"0", "1"}:
        raise HwImageError(f"{what} {bits!r} must be 0/1 (the harness is 2-state)")


class ImageBuilder:
    """Builds one slot's program. ``set_bits`` takes the whole next in_vec (MSB first)
    and emits a SET per changed chunk plus one COMMIT: one atomic input change."""

    def __init__(self, nin: int, nclk: int, noutw: int, t0: str) -> None:
        self.nin, self.nclk, self.noutw = nin, nclk, noutw
        w = width(nin)
        _check_bits(t0, w, "t0")
        if (w + CHUNK - 1) // CHUNK > MAX_CHUNKS or nclk > MAX_CLOCKS:
            raise HwImageError(f"nin={nin} nclk={nclk} exceed the harness's operand fields")
        self.t0 = t0
        self._cur = t0
        self._words: list[int] = []
        self._labels: list[str] = []

    def set_bits(self, bits: str) -> None:
        _check_bits(bits, width(self.nin), "in_vec")
        old, new = chunks(self._cur), chunks(bits)
        changed = [i for i, (a, b) in enumerate(zip(old, new, strict=True)) if a != b]
        if not changed:
            return
        self._words += [w_set(i, new[i]) for i in changed] + [w_commit()]
        self._cur = bits

    def edge(self, idx: int, level: int) -> None:
        if not 0 <= idx < self.nclk:
            raise HwImageError(f"clock {idx} out of range (nclk={self.nclk})")
        self._words.append(w_edge(idx, level))

    def wait(self, n: int) -> None:
        self._words.append(w_wait(n))

    def sample(self, label: str) -> None:
        self._words.append(W_SAMPLE)
        self._labels.append(label)

    def end(self, maxwords: int = MAXWORDS) -> HwProgram:
        words = [*self._words, W_END]
        if len(words) > maxwords:
            raise HwImageError(f"{len(words)} words > the harness's maxwords={maxwords}")
        return HwProgram(
            self.nin, self.nclk, self.noutw, self.t0, tuple(words), tuple(self._labels)
        )
