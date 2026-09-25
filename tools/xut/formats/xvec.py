# SPDX-License-Identifier: Apache-2.0
"""The ``.xvec`` stimulus format (spec §5.3). Standard library only.

Grammar (``#`` starts a comment everywhere except the header line)::

    file      := header NL { line NL }
    header    := "# xut-vec 2" { SP key "=" token }
                 required: prim cfg nin nout nclk settle_ps seed
                 optional: async_sep_ps expect illegal attr.<NAME>
                 (illegal=<NAME>[,<NAME>...]: the attributes an expect=reject
                 configuration makes illegal; xut.validate requires it there)
    line      := [ directive ] [ "#" comment ]
    directive := "clock" SP clk SP "period=" INT SP "phase=" INT SP "duty=" INT
                     SP "mode=" ( "stepped" | "free" )
               | "hw_renderable" SP ( "yes" | "no" SP "reason=" QUOTED )
               | "t=" INT [ SP "simultaneous" ] SP op
    op        := "set" SP "in[" INT [ ":" INT ] "]=" value
               | "edge" SP clk SP ( "r" | "f" )
               | "glbl" SP ( "GSR" | "GTS" | "GRESTORE" ) "=" ( "0" | "1" )
               | "sample" SP label
               | "clock_start" SP clk | "clock_stop" SP clk
               | "end"
    clk       := "clk" INT                     (index into the wrapper's clk vector)
    value     := "0x" HEX+ | "0b" ( "0"|"1"|"x"|"z" )+ | DECIMAL
    label     := [A-Za-z0-9_./-]+           (the shared grammar of xut.formats.common)

Times are integer picoseconds and never decrease. Before ``settle_ps`` only
``t=0 set`` initialisation lines may appear. ``in[msb:lsb]`` values are stored
MSB-first as characters of ``01xz``. Class rules (spec §5.1) are checked by
``xut.validate``, not here: this module is syntax and self-consistency only.

A ``#`` starts a comment everywhere it appears outside a double-quoted
string on a body line; a ``#`` inside ``reason="..."`` (or any other quoted
token) is data, not a comment. The writer never silently alters a value to
make it fit the format: a header value or ``hw_renderable`` reason that
contains a literal ``"`` or a newline cannot be represented and raises
``XvecError`` instead of being mangled.

Co-timed events (events sharing a ``t``): multiple ``set`` events at the
same time are allowed *without* ``simultaneous`` exactly when their
``in[msb:lsb]`` bit ranges are disjoint — they commute as one atomic input
change. Overlapping ``set`` ranges at the same time are always an error,
``simultaneous`` or not. Any other co-timed combination — a non-``set``
event sharing a ``t`` with anything, or two ``set``s whose ranges overlap —
requires ``simultaneous`` on *every* event at that ``t``; an unmarked
non-``set`` group is an error. A mix of marked and unmarked events at one ``t``
is always an error, disjoint ``set``s included (the marking would be ambiguous). A lone
event marked ``simultaneous`` (nothing else at its ``t``) is also an error.

The same rules hold for a ``Vec`` built in memory: ``check_structure`` applies every
per-line rule of the parser (via the shared ``_check_event``) plus a write/read round
trip, so the builder and the validator can never approve what the parser refuses.

Explicitly deferred (not supported yet):

- glbl channel: only ``GSR``, ``GTS`` and ``GRESTORE``. The ``JTAG_*`` signals that
  spec §5.2 also routes through glbl (used by BSCANE2) have no grammar yet; they
  arrive with the configuration group.
- DRP transactions (spec §5.5) have no representation here: ``drp``-class bits are
  driven with plain ``set`` lines and validated as data for now.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from xut.formats.common import FormatError, is_header_key, is_label

MAGIC = "xut-vec"
VERSION = 2
REQUIRED = ("prim", "cfg", "nin", "nout", "nclk", "settle_ps", "seed")
INT_KEYS = ("nin", "nout", "nclk", "settle_ps", "seed", "async_sep_ps")
HEADER_ORDER = REQUIRED + ("async_sep_ps", "expect", "illegal")

_HEADER = re.compile(r"^#\s*xut-vec\s+(\d+)\b(.*)$")
_KV = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S+)')
_CLOCK = re.compile(
    r"^clock\s+(clk(\d+))\s+period=(\d+)\s+phase=(\d+)\s+duty=(\d+)\s+mode=(stepped|free)$"
)
_HW = re.compile(r'^hw_renderable\s+(?:(yes)|no\s+reason="((?:[^"\\]|\\.)*)")$')
_EVENT = re.compile(r"^t=(\d+)\s+(?:(simultaneous)\s+)?(\w+)(?:\s+(.*))?$")
_SET = re.compile(r"^in\[(\d+)(?::(\d+))?\]=(\S+)$")
_EDGE = re.compile(r"^(clk\d+)\s+([rf])$")
_GLBL = re.compile(r"^(GSR|GTS|GRESTORE)=([01])$")


class XvecError(FormatError):
    """Syntax or self-consistency error, with the 1-based line number when known."""


@dataclass(frozen=True)
class Clock:
    name: str
    index: int
    period: int
    phase: int
    duty: int
    mode: str  # "stepped" | "free"


@dataclass(frozen=True)
class Event:
    t: int
    op: str  # set | edge | glbl | sample | clock_start | clock_stop | end
    target: str = ""  # set: "in"; edge/clock_*: clock name; glbl: signal; sample: label
    lsb: int = 0
    msb: int = 0
    value: str = ""  # set: MSB-first 01xz; edge: r|f; glbl: 0|1
    simultaneous: bool = False


@dataclass
class Vec:
    header: dict[str, str]
    clocks: list[Clock] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    hw_renderable: bool | None = None
    hw_reason: str = ""

    @property
    def prim(self) -> str:
        return self.header["prim"]

    @property
    def cfg(self) -> str:
        return self.header["cfg"]

    def _int(self, key: str) -> int:
        raw = self.header[key]
        try:
            return int(raw)
        except ValueError as exc:
            raise XvecError(f"header {key}={raw!r} is not an integer") from exc

    @property
    def nin(self) -> int:
        return self._int("nin")

    @property
    def nout(self) -> int:
        return self._int("nout")

    @property
    def nclk(self) -> int:
        return self._int("nclk")

    @property
    def settle_ps(self) -> int:
        return self._int("settle_ps")

    @property
    def seed(self) -> int:
        return self._int("seed")

    @property
    def expect(self) -> str | None:
        return self.header.get("expect")

    @property
    def illegal(self) -> list[str]:
        """The attributes an ``expect=reject`` configuration declares illegal (header
        ``illegal=<NAME>[,<NAME>...]``; ruling S13b)."""
        return [n for n in self.header.get("illegal", "").split(",") if n]

    @property
    def attrs(self) -> dict[str, str]:
        return {k[5:]: v for k, v in self.header.items() if k.startswith("attr.")}

    def clock(self, name: str) -> Clock:
        for c in self.clocks:
            if c.name == name:
                return c
        raise KeyError(name)


def decode_value(text: str, width: int, line: int | None = None, field: str | None = None) -> str:
    """Return ``text`` as exactly ``width`` MSB-first characters of ``01xz``.

    Leading zeros are fine (``0x00f`` fits in 4 bits), but any non-zero,
    ``x`` or ``z`` bit at or above ``width`` is a fit error, not a silent
    truncation. ``field`` (e.g. ``"in[3:0]"``), when given, names the
    over-wide field in the error message.
    """
    t = text.lower()
    if t.startswith("0b"):
        bits = t[2:]
        if not bits or set(bits) - set("01xz"):
            raise XvecError(f"bad binary value {text!r}", line)
    elif t.startswith("0x"):
        if not re.fullmatch(r"[0-9a-f]+", t[2:]):  # int() would accept "-1", "+1", "1_0"
            raise XvecError(f"bad hex value {text!r}", line)
        bits = format(int(t[2:], 16), "b")
    elif re.fullmatch(r"[0-9]+", t):
        bits = format(int(t), "b")
    else:
        raise XvecError(f"bad value {text!r}", line)
    if len(bits) > width and set(bits[: len(bits) - width]) != {"0"}:
        where = f"{field}: " if field else ""
        raise XvecError(f"{where}value {text!r} does not fit in {width} bit(s)", line)
    return bits[-width:].rjust(width, "0")


def encode_value(bits: str) -> str:
    if set(bits) <= {"0", "1"}:
        return bits if len(bits) == 1 else f"0x{int(bits, 2):x}"
    return "0b" + bits


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def _strip_comment(raw: str) -> str:
    """Return ``raw`` with a trailing ``#`` comment removed, honouring
    double-quoted strings: a ``#`` inside an (optionally backslash-escaped)
    quoted token is data, not the start of a comment."""
    in_quotes = False
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "\\" and in_quotes:
            i += 2
            continue
        if c == '"':
            in_quotes = not in_quotes
        elif c == "#" and not in_quotes:
            return raw[:i]
        i += 1
    return raw


def _escape_quoted(v: str, what: str) -> str:
    """Escape ``v`` for embedding inside a double-quoted token, or raise if it
    cannot be represented: this format has no way to encode a literal quote
    inside a bare/quoted token or a newline within a single line, and the
    writer never silently mangles data to work around that."""
    if '"' in v or "\n" in v or "\r" in v:
        raise XvecError(f"{what} {v!r} cannot be represented (contains a quote or newline)")
    return v.replace("\\", "\\\\")


def _quote(v: str, what: str = "value") -> str:
    if v and not re.search(r'[\s"#]', v):
        return v
    return f'"{_escape_quoted(v, what)}"'


def _event(vec: Vec, t: int, op: str, arg: str, sim: bool, labels: set[str], n: int) -> Event:
    """Parse one event's operand text (syntax only), then apply the shared per-event
    rules of ``_check_event``."""
    if op == "set":
        m = _SET.match(arg)
        if not m:
            raise XvecError(f"bad set target {arg!r}", n)
        msb = int(m.group(1))
        lsb = int(m.group(2)) if m.group(2) is not None else msb
        if lsb > msb:
            raise XvecError(f"in[{msb}:{lsb}]: msb < lsb", n)
        if msb >= vec.nin:
            raise XvecError(f"in[{msb}] out of range (nin={vec.nin})", n)
        rng = str(msb) if lsb == msb else f"{msb}:{lsb}"
        value = decode_value(m.group(3), msb - lsb + 1, n, field=f"in[{rng}]")
        e = Event(t, "set", "in", lsb, msb, value, sim)
    elif op == "edge":
        m = _EDGE.match(arg)
        if not m:
            raise XvecError(f"edge on undeclared clock {arg!r}", n)
        e = Event(t, "edge", m.group(1), value=m.group(2), simultaneous=sim)
    elif op == "glbl":
        m = _GLBL.match(arg)
        if not m:
            raise XvecError(f"bad glbl event {arg!r}", n)
        e = Event(t, "glbl", m.group(1), value=m.group(2), simultaneous=sim)
    elif op == "end":
        if arg:
            raise XvecError("'end' takes no argument", n)
        e = Event(t, "end", simultaneous=sim)
    else:  # sample, clock_start, clock_stop, or an unknown op (refused below)
        e = Event(t, op, arg, simultaneous=sim)
    try:
        _check_event(vec, e, labels)
    except XvecError as x:
        raise XvecError(str(x), n) from x
    return e


def _check_header(header: dict[str, str]) -> None:
    """Header keys, required keys and integer values (shared by parser and writer)."""
    for k, v in header.items():
        if not is_header_key(k):
            raise XvecError(f"header key {k!r} is not [A-Za-z_][A-Za-z0-9_.]*")
        if not isinstance(v, str):
            raise XvecError(f"header {k}={v!r} must be a string")
    missing = [k for k in REQUIRED if k not in header]
    if missing:
        raise XvecError(f"header lacks {', '.join(missing)}")
    for k in INT_KEYS:
        if k in header and not (header[k].isascii() and header[k].isdigit()):
            raise XvecError(f"header {k} must be a non-negative integer")


def _check_clock(vec: Vec, c: Clock, names: set[str]) -> None:
    if c.name != f"clk{c.index}" or not 0 <= c.index < vec.nclk or c.name in names:
        raise XvecError(f"clock {c.name}: index out of range or declared twice")
    names.add(c.name)
    if c.period <= 0 or not 0 < c.duty < 100:
        raise XvecError(f"clock {c.name}: period must be > 0 and 0 < duty < 100")
    if c.phase < 0:
        raise XvecError(f"clock {c.name}: phase must be >= 0")
    if c.mode not in ("stepped", "free"):
        raise XvecError(f"clock {c.name}: mode must be stepped or free, got {c.mode!r}")


def _check_event(vec: Vec, e: Event, labels: set[str]) -> None:
    """THE per-event rules, applied by the parser to every line and by
    ``check_structure`` to every in-memory event (review A2): settle window, bit
    range, value width, declared clocks, glbl signals, label grammar and uniqueness."""
    if not isinstance(e.t, int) or e.t < 0:
        raise XvecError(f"negative or non-integer time {e.t!r}")
    if e.t < vec.settle_ps and not (e.t == 0 and e.op == "set"):
        raise XvecError(f"only 't=0 set' initialisation may precede settle_ps={vec.settle_ps}")
    if e.op == "set":
        if e.target != "in":
            raise XvecError(f"set target must be 'in', got {e.target!r}")
        if e.lsb > e.msb:
            raise XvecError(f"in[{e.msb}:{e.lsb}]: msb < lsb")
        if e.lsb < 0 or e.msb >= vec.nin:
            raise XvecError(f"in[{e.msb}] out of range (nin={vec.nin})")
        width = e.msb - e.lsb + 1
        if len(e.value) != width or set(e.value) - set("01xz"):
            raise XvecError(f"in[{e.msb}:{e.lsb}]: value {e.value!r} is not {width} bit(s) of 01xz")
        return
    if e.op not in ("glbl", "edge") and e.value:
        raise XvecError(f"{e.op} takes no value, got {e.value!r}")
    if e.op == "edge":
        if e.target not in {c.name for c in vec.clocks}:
            raise XvecError(f"edge on undeclared clock {e.target!r}")
        if e.value not in ("r", "f"):
            raise XvecError(f"edge value must be r or f, got {e.value!r}")
    elif e.op == "glbl":
        if e.target not in ("GSR", "GTS", "GRESTORE") or e.value not in ("0", "1"):
            raise XvecError(f"bad glbl event {e.target}={e.value}")
    elif e.op == "sample":
        if not is_label(e.target):
            raise XvecError(f"bad sample label {e.target!r}")
        if e.target in labels:
            raise XvecError(f"duplicate label {e.target!r}")
        labels.add(e.target)
    elif e.op in ("clock_start", "clock_stop"):
        if not any(c.name == e.target and c.mode == "free" for c in vec.clocks):
            raise XvecError(f"{e.op} needs a declared mode=free clock, got {e.target!r}")
    elif e.op == "end":
        if e.target:
            raise XvecError("'end' takes no argument")
    else:
        raise XvecError(f"unknown op {e.op!r}")


def check_structure(vec: Vec) -> None:
    """Every rule the parser applies, for a ``Vec`` built in memory rather than parsed
    (review A2): header keys and integers, clock declarations, the per-event rules of
    ``_check_event`` (settle window, bit range, declared clocks, label syntax and
    uniqueness), time order, ``end`` last, co-timing and ``simultaneous`` marking.
    Finally the Vec must survive ``loads(dumps(vec))`` unchanged, so an in-memory Vec
    that would not parse back is always an error. Raises ``XvecError`` naming events
    by 1-based position (``event #N``)."""
    _check_header(vec.header)
    names: set[str] = set()
    for c in vec.clocks:
        _check_clock(vec, c, names)
    labels: set[str] = set()
    for i, e in enumerate(vec.events):
        try:
            _check_event(vec, e, labels)
        except XvecError as x:
            raise XvecError(f"event #{i + 1}: {x}") from x
    _check_structure(vec, None)
    if loads(dumps(vec)) != vec:
        raise XvecError("the stimulus does not survive a write/read round trip unchanged")


def checkable(vec: Vec) -> Vec:
    """The part of an in-memory ``vec`` that satisfies the per-item rules: the clocks
    and events that ``check_structure`` would not refuse on their own. ``xut.validate``
    uses it to keep reporting class-rule errors after a structure error, without
    crashing (an out-of-range bit) or hanging (a zero clock period). Raises
    ``XvecError`` if the header itself is unusable."""
    _check_header(vec.header)
    clocks: list[Clock] = []
    names: set[str] = set()
    for c in vec.clocks:
        try:
            _check_clock(vec, c, names)
        except XvecError:
            continue
        clocks.append(c)
    out = Vec(dict(vec.header), clocks, [], vec.hw_renderable, vec.hw_reason)
    events = []
    for e in vec.events:
        try:
            _check_event(out, e, set())
        except XvecError:
            continue
        events.append(e)
    out.events = sorted(events, key=lambda e: e.t)
    return out


def _check_structure(vec: Vec, event_lines: list[int] | None) -> None:
    ev = vec.events
    if event_lines is None:
        unit, names, lines = "event", [f"#{i + 1}" for i in range(len(ev))], [None] * len(ev)
    else:
        unit, names, lines = "line", [str(n) for n in event_lines], list(event_lines)

    def at(i: int) -> str:
        return "" if event_lines is not None else f" ({unit} {names[i]})"

    for i, e in enumerate(ev):
        if i and e.t < ev[i - 1].t:
            raise XvecError(f"time goes backwards ({e.t} < {ev[i - 1].t}){at(i)}", lines[i])
        if e.op == "end" and i != len(ev) - 1:
            raise XvecError(f"'end' must be the last event{at(i)}", lines[i])

    groups: dict[int, list[int]] = {}
    for i, e in enumerate(ev):
        groups.setdefault(e.t, []).append(i)

    for t, idxs in groups.items():
        if len(idxs) == 1:
            i = idxs[0]
            if ev[i].simultaneous:
                raise XvecError(
                    f"t={t}: 'simultaneous' on an event that is alone at its time{at(i)}",
                    lines[i],
                )
            continue
        unmarked = [names[i] for i in idxs if not ev[i].simultaneous]
        if 0 < len(unmarked) < len(idxs):
            # Mixed marking is ambiguous (were the unmarked events meant to be at the
            # same instant or not?) and is refused for every group, disjoint sets included.
            raise XvecError(
                f"t={t}: mixed 'simultaneous' marking: mark every event at this time or "
                f"none (unmarked at {unit}(s) {', '.join(unmarked)})",
            )
        if all(ev[i].op == "set" for i in idxs):
            # Disjoint 'set' ranges commute as one atomic input change and need no
            # 'simultaneous' marking; overlapping ranges are always an error.
            for a in range(len(idxs)):
                lsb_a, msb_a = ev[idxs[a]].lsb, ev[idxs[a]].msb
                for b in range(a + 1, len(idxs)):
                    lsb_b, msb_b = ev[idxs[b]].lsb, ev[idxs[b]].msb
                    if lsb_a <= msb_b and lsb_b <= msb_a:
                        raise XvecError(
                            f"t={t}: overlapping 'set' bit ranges at {unit}s "
                            f"{names[idxs[a]]} and {names[idxs[b]]}",
                        )
            continue
        # A non-'set' event sharing this t with anything else (or a 'set' mixed
        # with a non-'set') requires 'simultaneous' on every event at this t.
        if unmarked:
            raise XvecError(
                f"t={t}: co-timed events require 'simultaneous' on every event at "
                f"this time (unmarked at {unit}(s) {', '.join(unmarked)})",
            )


def loads(text: str) -> Vec:
    lines = text.splitlines()
    if not lines:
        raise XvecError("empty file")
    m = _HEADER.match(lines[0])
    if not m:
        raise XvecError("first line must be '# xut-vec 2 ...'", 1)
    if int(m.group(1)) != VERSION:
        raise XvecError(f"unsupported xut-vec version {m.group(1)}", 1)
    header = {k: _unquote(v) for k, v in _KV.findall(m.group(2))}
    try:
        _check_header(header)
    except XvecError as x:
        raise XvecError(str(x), 1) from x
    vec = Vec(header)
    labels: set[str] = set()
    event_lines: list[int] = []
    for n, raw in enumerate(lines[1:], start=2):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if c := _CLOCK.match(line):
            name, idx, period, phase, duty, mode = c.groups()
            clk = Clock(name, int(idx), int(period), int(phase), int(duty), mode)
            try:
                _check_clock(vec, clk, {k.name for k in vec.clocks})
            except XvecError as x:
                raise XvecError(str(x), n) from x
            vec.clocks.append(clk)
            continue
        if h := _HW.match(line):
            vec.hw_renderable = h.group(1) == "yes"
            vec.hw_reason = _unquote(f'"{h.group(2)}"') if h.group(2) is not None else ""
            continue
        e = _EVENT.match(line)
        if not e:
            raise XvecError(f"unrecognised line {raw.strip()!r}", n)
        t, sim, op, arg = int(e.group(1)), bool(e.group(2)), e.group(3), (e.group(4) or "").strip()
        vec.events.append(_event(vec, t, op, arg, sim, labels, n))
        event_lines.append(n)
    _check_structure(vec, event_lines)
    return vec


def _fmt(e: Event) -> str:
    head = f"t={e.t}" + (" simultaneous" if e.simultaneous else "")
    if e.op == "set":
        rng = str(e.msb) if e.msb == e.lsb else f"{e.msb}:{e.lsb}"
        return f"{head}  set in[{rng}]={encode_value(e.value)}"
    if e.op == "edge":
        return f"{head}  edge {e.target} {e.value}"
    if e.op == "glbl":
        return f"{head}  glbl {e.target}={e.value}"
    if e.op == "end":
        return f"{head}  end"
    return f"{head}  {e.op} {e.target}"


def dumps(vec: Vec) -> str:
    """The stimulus as text. Raises ``XvecError`` on a header key, header value, sample
    label or reason that the format cannot represent (never silently altered)."""
    for k in vec.header:
        if not is_header_key(k):
            raise XvecError(f"header key {k!r} is not [A-Za-z_][A-Za-z0-9_.]*")
    for e in vec.events:
        if e.op == "sample" and not is_label(e.target):
            raise XvecError(f"sample label {e.target!r} is not [A-Za-z0-9_./-]+")
    keys = [k for k in HEADER_ORDER if k in vec.header]
    keys += sorted(k for k in vec.header if k not in HEADER_ORDER)
    out = [
        f"# {MAGIC} {VERSION}  "
        + " ".join(f"{k}={_quote(vec.header[k], f'header {k}')}" for k in keys)
    ]
    if vec.hw_renderable is not None:
        if vec.hw_renderable:
            out.append("hw_renderable yes")
        else:
            reason = _escape_quoted(vec.hw_reason, "hw_reason")
            out.append(f'hw_renderable no reason="{reason}"')
    for c in vec.clocks:
        out.append(f"clock {c.name} period={c.period} phase={c.phase} duty={c.duty} mode={c.mode}")
    out += [_fmt(e) for e in vec.events]
    return "\n".join(out) + "\n"


def load(path: Path) -> Vec:
    return loads(Path(path).read_text())


def dump(vec: Vec, path: Path) -> None:
    Path(path).write_text(dumps(vec))


def digest(vec: Vec) -> str:
    return hashlib.sha256(dumps(vec).encode()).hexdigest()


def free_runs(vec: Vec) -> list[tuple[Clock, int, int | None]]:
    """(clock, start, stop) for every mode=free clock. A free clock with no clock_start
    runs from max(0, phase); stop is None when it runs to the end of the file."""
    runs, open_ = [], {}
    for c in vec.clocks:
        if c.mode == "free" and not any(
            e.op == "clock_start" and e.target == c.name for e in vec.events
        ):
            open_[c.name] = max(0, c.phase)
    for e in vec.events:
        if e.op == "clock_start":
            open_[e.target] = e.t
        elif e.op == "clock_stop" and e.target in open_:
            runs.append((vec.clock(e.target), open_.pop(e.target), e.t))
    return runs + [(vec.clock(n), t0, None) for n, t0 in open_.items()]


def free_clock_edges(vec: Vec) -> list[Event]:
    """THE definition of free-clock edges, shared by xut.validate, xut.golden and
    xut.stimcompile (review #6): a rise at start + k*period, a fall period*duty/100
    later, nothing at or after a clock_stop (validate requires a stop to fall strictly
    inside a low phase, which is exactly where the testbench's generator stops), and
    nothing after the last event."""
    end = vec.events[-1].t if vec.events else 0
    out: list[Event] = []
    for c, start, stop in free_runs(vec):
        limit = end if stop is None else stop - 1
        high, t = c.period * c.duty // 100, start
        while t <= limit:
            out.append(Event(t, "edge", c.name, value="r"))
            if t + high <= limit:
                out.append(Event(t + high, "edge", c.name, value="f"))
            t += c.period
    return sorted(out, key=lambda e: e.t)
