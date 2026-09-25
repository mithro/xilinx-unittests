# SPDX-License-Identifier: Apache-2.0
"""The ``.xvec`` stimulus format (spec §5.3). Standard library only.

Grammar (``#`` starts a comment everywhere except the header line)::

    file      := header NL { line NL }
    header    := "# xut-vec 2" { SP key "=" token }
                 required: prim cfg nin nout nclk settle_ps seed
                 optional: async_sep_ps expect attr.<NAME>
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
    label     := [A-Za-z0-9_./-]+

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
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = "xut-vec"
VERSION = 2
REQUIRED = ("prim", "cfg", "nin", "nout", "nclk", "settle_ps", "seed")
INT_KEYS = ("nin", "nout", "nclk", "settle_ps", "seed", "async_sep_ps")
HEADER_ORDER = REQUIRED + ("async_sep_ps", "expect")

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
_LABEL = re.compile(r"^[A-Za-z0-9_./-]+$")


class XvecError(ValueError):
    """Syntax or self-consistency error, with the 1-based line number when known."""

    def __init__(self, msg: str, line: int | None = None) -> None:
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


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
    declared = {c.name for c in vec.clocks}
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
        return Event(t, "set", "in", lsb, msb, value, sim)
    if op == "edge":
        m = _EDGE.match(arg)
        if not m or m.group(1) not in declared:
            raise XvecError(f"edge on undeclared clock {arg!r}", n)
        return Event(t, "edge", m.group(1), value=m.group(2), simultaneous=sim)
    if op == "glbl":
        m = _GLBL.match(arg)
        if not m:
            raise XvecError(f"bad glbl event {arg!r}", n)
        return Event(t, "glbl", m.group(1), value=m.group(2), simultaneous=sim)
    if op == "sample":
        if not _LABEL.match(arg):
            raise XvecError(f"bad sample label {arg!r}", n)
        if arg in labels:
            raise XvecError(f"duplicate label {arg!r}", n)
        labels.add(arg)
        return Event(t, "sample", arg, simultaneous=sim)
    if op in ("clock_start", "clock_stop"):
        if arg not in declared or vec.clock(arg).mode != "free":
            raise XvecError(f"{op} needs a declared mode=free clock, got {arg!r}", n)
        return Event(t, op, arg, simultaneous=sim)
    if op == "end":
        if arg:
            raise XvecError("'end' takes no argument", n)
        return Event(t, "end", simultaneous=sim)
    raise XvecError(f"unknown op {op!r}", n)


def check_structure(vec: Vec) -> None:
    """The parser's structural rules (time order, ``end`` last, co-timing and
    ``simultaneous`` marking) for a ``Vec`` built in memory rather than parsed.
    Raises ``XvecError`` naming events by 1-based position (``event #N``)."""
    _check_structure(vec, None)


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
    missing = [k for k in REQUIRED if k not in header]
    if missing:
        raise XvecError(f"header lacks {', '.join(missing)}", 1)
    for k in INT_KEYS:
        if k in header and not header[k].isdigit():
            raise XvecError(f"header {k} must be a non-negative integer", 1)
    vec = Vec(header)
    labels: set[str] = set()
    last_t = 0
    event_lines: list[int] = []
    for n, raw in enumerate(lines[1:], start=2):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if c := _CLOCK.match(line):
            name, idx, period, phase, duty, mode = c.groups()
            if int(idx) >= vec.nclk or any(k.name == name for k in vec.clocks):
                raise XvecError(f"clock {name}: index out of range or declared twice", n)
            if int(period) <= 0 or not 0 < int(duty) < 100:
                raise XvecError(f"clock {name}: period must be > 0 and 0 < duty < 100", n)
            vec.clocks.append(Clock(name, int(idx), int(period), int(phase), int(duty), mode))
            continue
        if h := _HW.match(line):
            vec.hw_renderable = h.group(1) == "yes"
            vec.hw_reason = _unquote(f'"{h.group(2)}"') if h.group(2) is not None else ""
            continue
        e = _EVENT.match(line)
        if not e:
            raise XvecError(f"unrecognised line {raw.strip()!r}", n)
        t, sim, op, arg = int(e.group(1)), bool(e.group(2)), e.group(3), (e.group(4) or "").strip()
        if t < last_t:
            raise XvecError(f"time goes backwards ({t} < {last_t})", n)
        if t < vec.settle_ps and not (t == 0 and op == "set"):
            raise XvecError(
                f"only 't=0 set' initialisation may precede settle_ps={vec.settle_ps}", n
            )
        last_t = t
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
