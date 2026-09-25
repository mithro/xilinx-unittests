# SPDX-License-Identifier: Apache-2.0
"""Parse primitive sections out of ``pdftotext -layout`` output of UG953.

The text is a PDF rendering, so tables are only aligned by column position:

* cells wrap onto several lines and are vertically centred on the row, so the
  "anchor" line holding the row's type/direction token may not hold its name;
* names wrap (``RDADDR`` / ``_COLLISION`` / ``_HWCONFIG``), are grouped
  (``DOA_REG,`` / ``DOB_REG``) or given as ranges (``INIT_00 to INIT_7F``,
  ``Q1 - Q8``);
* adjacent cells are sometimes separated by a single space;
* tables continue over page breaks (footer, running header, repeated table
  header) and contain full-width prose paragraphs.

The parser therefore finds anchor lines (a direction or type token in its
column), chains column-0 name fragments that continue each other, classifies the
other text runs by column (estimated per page from the rows and the repeated
table header), and gives each value fragment to the cell it continues (an open
quote or a trailing comma) or else to the nearest anchor.

The printed page number of a line is taken from the next page footer at or
after it (``pdftotext`` puts each page's footer at the bottom of that page).

Only facts (names, widths, values) and short fragments (at most
``MAX_FRAGMENT`` characters) of AMD's text are kept.
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import median

MAX_FRAGMENT = 120

_FOOTER = re.compile(r"^UG953 v[\d.]+\s+(\d+)\s*$")
_DATE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}\s*$")
_SECTION_KINDS = ("Primitive:", "Macro:", "Parameterized Macro:")
_HEADINGS = frozenset(
    {
        "Introduction",
        "Logic Table",
        "Port Descriptions",
        "Design Entry Method",
        "Available Attributes",
        "VHDL Instantiation Template",
        "Verilog Instantiation Template",
        "Related Information",
    }
)

_PAGEBREAK = object()

# One identifier-ish fragment in the name column (``INIT_00 to``, ``DOA_REG,``,
# ``SRVAL_A, SRVAL_B``, ``CLKOUT0_DIVIDE _F``, ``_CYCLE``).
_ID = r"[A-Z_][A-Z0-9_]*(?: _[A-Z0-9_]+)*"
_NAMEFRAG = rf"{_ID}(?:,\s*{_ID})*,?(?: to(?: {_ID})?)?"
_TYPES = "BINARY|HEX|DECIMAL|STRING|FLOAT|INTEGER|BOOLEAN|REAL"
_ATTR_ANCHOR = re.compile(
    rf"^(?P<name>{_NAMEFRAG})?(?P<gap>\s+)(?:\d significant\s+)?(?:digit\s+)?"
    rf"(?P<cell>(?P<type>{_TYPES})(?:\s?\([^)]*\)| MHz)?)(?=\s|$)(?P<rest>.*)$"
)
# A name fragment at column 0; a single space followed by lowercase text means prose.
_NAME_AT_START = re.compile(rf"^(?P<name>{_NAMEFRAG})(?=\s|$)(?! [a-z])")
_TYPE_MAX_COL = 45
_SIGNIFICANT = re.compile(r"\d significant")

_BUS = r"(?:\s*[<\[]\d+:\d+[>\]])?"
_PID = rf"[A-Z][A-Za-z0-9_]*{_BUS}"
_PORT_ANCHOR = re.compile(
    rf"^(?P<name>{_PID}(?:\s*[,:/-]\s*{_PID})*)\s+(?P<dir>[A-Z][a-z]+)\s+"
    rf"(?P<width>\d+)(?:\s*\(each\))?(?:\s{{2,}}(?P<func>\S.*))?\s*$"
)
_DIRECTIONS = {"Input": "input", "Output": "output", "Inout": "inout"}

_DEFAULT_PHRASE = re.compile(r"^(?P<allowed>.*\S)\s+(?P<default>All (?:zeros|zeroes|ones))$")
_TRAILING_DEFAULT = re.compile(
    r"^(?P<allowed>.*(?:,| to ).*[\w\"'])\s(?P<default>-?[\d.]+|\"[^\"]*\"|TRUE|FALSE"
    r"|\d+'[bhdBHD][0-9A-Fa-f_]+)$"
)


@dataclass
class DocSection:
    name: str
    description: str
    group: str
    subgroup: str
    page: int
    ports: dict[str, dict] = field(default_factory=dict)
    attributes: dict[str, dict] = field(default_factory=dict)
    design_entry: dict[str, str] = field(default_factory=dict)
    has_logic_table: bool = False
    # cells the parser could not read reliably, e.g. "port TODD function"
    review: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- utils


def _fragment(text: str) -> str:
    """First sentence of ``text``, capped at MAX_FRAGMENT characters."""
    text = " ".join(text.split())
    m = re.match(r"(.+?\.)(?:\s|$)", text)
    if m:
        text = m.group(1)
    return text[:MAX_FRAGMENT].rstrip()


def _runs(line: str, start: int = 0) -> list[tuple[int, str]]:
    """Text runs separated by 2+ spaces, with their start columns."""
    return [(m.start() + start, m.group()) for m in re.finditer(r"\S+(?: \S+)*", line[start:])]


def _page_numbers(lines: list[str]) -> list[int]:
    """Printed page number for every line: the next footer at or after it."""
    pages = [0] * len(lines)
    nxt = None
    for i in range(len(lines) - 1, -1, -1):
        m = _FOOTER.match(lines[i])
        if m:
            if nxt is None:
                # lines after the final footer belong to the page after it
                pages[i + 1 :] = [int(m.group(1)) + 1] * (len(lines) - i - 1)
            nxt = int(m.group(1))
        pages[i] = nxt or 0
    return pages


def _clean(lines: list[str]) -> list:
    """Drop page furniture; each page break becomes a single _PAGEBREAK marker."""
    out: list = []
    skip_header = False
    for ln in lines:
        s = ln.strip()
        if _FOOTER.match(ln):
            out.append(_PAGEBREAK)
            skip_header = False
            continue
        if s == "Send Feedback":
            continue
        if _DATE.match(ln):
            skip_header = True
            continue
        if skip_header and s:
            skip_header = False
            if len(ln) - len(ln.lstrip()) >= 30:
                continue  # running page header ("Design Elements")
        out.append(ln)
    return out


def _is_start(lines: list[str], i: int) -> bool:
    return (
        bool(lines[i])
        and not lines[i][0].isspace()
        and i + 1 < len(lines)
        and lines[i + 1].startswith(_SECTION_KINDS)
    )


def _blocks(body: list) -> dict[str, list]:
    blocks: dict[str, list] = {}
    cur = None
    for ln in body:
        if ln is not _PAGEBREAK and ln.rstrip() in _HEADINGS:
            cur = ln.rstrip()
            blocks.setdefault(cur, [])
            continue
        if cur is not None:
            blocks[cur].append(ln)
    return blocks


def _nearest(
    idx: float,
    anchors: list[int],
    barriers: list[int],
    prefer: Callable[[int], int],
    pos: dict[int, float] | None = None,
    penalty: Callable[[int], float] | None = None,
) -> int | None:
    """Index of the anchor nearest ``idx`` with no barrier in between.

    ``pos`` optionally maps an anchor to the (fractional) line its row is centred on;
    ``penalty(anchor)`` adds to the distance (e.g. the anchor already has that cell).
    """
    best = None
    for a in anchors:
        lo, hi = sorted((a, idx))
        if any(lo < b < hi for b in barriers):
            continue
        d = abs((pos or {}).get(a, a) - idx) + (penalty(a) if penalty else 0)
        if best is None or d < best[0]:
            best = (d, a)
        elif d == best[0]:
            # tie: prefer the anchor that is missing this kind of cell, else the later one
            pa, pb = prefer(a), prefer(best[1])
            if pa > pb or (pa == pb and a > best[1]):
                best = (d, a)
    return None if best is None else best[1]


# --------------------------------------------------------------------------- ports


def _expand_names(spec: str) -> list[tuple[str, int | None]]:
    """``A<4:0>`` / ``Q1 - Q8`` / ``CE1, CE2`` / ``S1 / S2`` -> [(name, bus_width)]."""
    parts = [p.strip() for p in re.split(r"\s*[,/]\s*|\s+[-:]\s+", spec) if p.strip()]
    ranged = re.search(r"\s+[-:]\s+", spec) is not None and len(parts) == 2
    out = []
    for p in parts:
        m = re.match(r"^([A-Za-z0-9_]+)\s*(?:[<\[](\d+):(\d+)[>\]])?$", p)
        if not m:
            continue
        w = abs(int(m.group(2)) - int(m.group(3))) + 1 if m.group(2) else None
        out.append((m.group(1), w))
    if ranged and len(out) == 2:
        names = _expand_range(out[0][0], out[1][0])
        if names:
            return [(n, None) for n in names]
    return out


def _parse_ports(block: list) -> tuple[dict[str, dict], list[str]]:
    anchors: dict[int, re.Match] = {}
    barriers: list[int] = []
    for i, ln in enumerate(block):
        if ln is _PAGEBREAK:
            barriers.append(i)
            continue
        if "Port" in ln and "Direction" in ln:
            barriers.append(i)
            continue
        m = _PORT_ANCHOR.match(ln.rstrip())
        if m and m.start("dir") < _TYPE_MAX_COL:
            anchors[i] = m
        elif ln[:1].strip():
            barriers.append(i)  # column-0 prose row
    first, unsure = _assign_functions(block, anchors, barriers)
    ports: dict[str, dict] = {}
    review: list[str] = []
    for i, m in anchors.items():
        direction = _DIRECTIONS.get(m.group("dir"))
        if direction is None:
            continue  # e.g. "Internal" (other families only)
        width = int(m.group("width"))
        func = "" if i in unsure else _fragment(first.get(i, ""))
        for name, bus_w in _expand_names(m.group("name")):
            ports[name] = {"direction": direction, "width": bus_w or width, "function": func}
            if i in unsure:
                review.append(f"port {name} function")
    return ports, review


_FUNC_MIN_COL = 20  # only the Function column is indented this far in a port table


def _assign_functions(
    block: list, anchors: dict[int, re.Match], barriers: list[int]
) -> tuple[dict[int, str], set[int]]:
    """First line of every row's Function cell, and the rows where it is uncertain.

    A Function cell is vertically centred on its row: a cell with ``u`` lines above
    the anchor line has ``u`` (or ``u`` +/- 1) lines below it. Walking down a page, the
    lines between two anchors are split so the next row's first line looks like the
    start of a cell (a capital at the column's left edge, not a bullet or a
    lowercase continuation). Rows where no split gives that are reported.
    """
    seg_of, seg = {}, 0
    for i in range(len(block)):
        if i in barriers:
            seg += 1
        seg_of[i] = seg
    desc = [
        i
        for i, ln in enumerate(block)
        if i not in anchors
        and i not in barriers
        and ln is not _PAGEBREAK
        and ln.strip()
        and len(ln) - len(ln.lstrip()) >= _FUNC_MIN_COL
    ]
    first: dict[int, str] = {}
    unsure: set[int] = set()
    for s in sorted({seg_of[a] for a in anchors}):
        rows = sorted(a for a in anchors if seg_of[a] == s)
        lines = [i for i in desc if seg_of[i] == s]
        inline = {a: anchors[a].start("func") for a in rows if anchors[a].group("func")}
        indents = [len(block[i]) - len(block[i].lstrip()) for i in lines] + list(inline.values())
        left = min(indents) if indents else 0

        def text_at(i: int, inline: dict[int, int] = inline) -> tuple[int, str]:
            if i in inline:
                return inline[i], anchors[i].group("func")
            return len(block[i]) - len(block[i].lstrip()), block[i].strip()

        def starts_cell(
            i: int, left: int = left, text_at: Callable[[int], tuple[int, str]] = text_at
        ) -> bool:
            col, text = text_at(i)
            return col <= left + 1 and bool(re.match(r"[A-Z0-9\"'(]", text))

        owned: dict[int, list[int]] = {a: [] for a in rows}
        owned[rows[0]] = [i for i in lines if i < rows[0]]
        for k, a in enumerate(rows):
            below = [i for i in lines if i > a and (k + 1 == len(rows) or i < rows[k + 1])]
            if k + 1 == len(rows):
                owned[a] += below
                break
            nxt = rows[k + 1]
            u = len(owned[a])
            split = None
            for d in (u, u + 1, u - 1):
                if 0 <= d <= len(below):
                    head = below[d] if d < len(below) else (nxt if nxt in inline else None)
                    if head is None or starts_cell(head):
                        split = d
                        break
            if split is None:
                split = min(max(u, 0), len(below))
            owned[a] += below[:split]
            owned[nxt] = below[split:]
        for a in rows:
            cell = sorted(owned[a] + ([a] if a in inline else []))
            if not cell:
                continue
            first[a] = text_at(cell[0])[1]
            if not starts_cell(cell[0]):
                unsure.add(a)
    return first, unsure


# --------------------------------------------------------------------------- attributes


def _expand_range(a: str, b: str) -> list[str] | None:
    """``INIT_00``..``INIT_7F`` / ``CLKOUT0_PHASE``..``CLKOUT6_PHASE`` -> every name."""
    p = 0
    while p < min(len(a), len(b)) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(len(a), len(b)) - p and a[-1 - s] == b[-1 - s]:
        s += 1
    while p and a[p - 1].isdigit():
        p -= 1
    while s and a[len(a) - s].isdigit():
        s -= 1
    ma, mb = a[p : len(a) - s], b[p : len(b) - s]
    if not ma or not mb or a[:p] != b[:p]:
        return None
    hexy = bool(re.search("[A-F]", ma + mb))
    if not re.fullmatch("[0-9A-F]+" if hexy else "[0-9]+", ma + mb):
        return None
    base = 16 if hexy else 10
    lo, hi = int(ma, base), int(mb, base)
    if hi < lo or hi - lo > 1024:
        return None
    width = len(ma) if ma.startswith("0") or len(ma) == len(mb) else 0
    spec = f"0{width}{'X' if hexy else 'd'}"
    pre, suf = a[:p], a[len(a) - s :]
    return [f"{pre}{v:{spec}}{suf}" for v in range(lo, hi + 1)]


def _join(frags: list[str]) -> str:
    """Join a value cell's fragments; a fragment inside an open quote was wrapped mid-word."""
    out = ""
    for f in frags:
        f = f.strip()
        if not out:
            out = f
        elif out.endswith("_") or f.startswith("_") or (out.count('"') % 2 and f[0] != '"'):
            out += f
        else:
            out += " " + f
    return out


def _continues(prev: str, frag: str, gap: int, prev_is_anchor: bool) -> bool:
    """Does column-0 name fragment ``frag`` continue ``prev`` (``gap`` lines below)?"""
    if gap > 3:
        return False
    if prev.endswith((",", " to", "_")) or frag.startswith("_"):
        return True
    # the short tail of a name wrapped mid-word ("CLKFBOUT_PHAS" / "E")
    return gap <= 2 and not prev_is_anchor and len(frag) <= 3 and not frag.endswith(",")


def _join_name(frags: list[str]) -> str:
    out = ""
    for f in frags:
        f = f.strip().replace(" _", "_")
        if not out:
            out = f
        elif out.endswith(",") or out.endswith(" to"):
            out += " " + f
        else:
            out += f  # wrapped mid-name
    return out


def _expand_open(a: str, b: str) -> list[str]:
    """``CLKFBOUT_X to CLKOUT6_X``: ``a`` plus the numbered family ``b`` counts up from 0."""
    m = re.fullmatch(r"(.*?[A-Z_])(\d+)(\D*)", b)
    if m and not re.search(r"\d", a) and int(m.group(2)) <= 64:
        return [a, *(f"{m.group(1)}{i}{m.group(3)}" for i in range(int(m.group(2)) + 1))]
    return [a, b]


def _attr_names(spec: str) -> list[str]:
    spec = spec.replace(" _", "_")
    names: list[str] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        m = re.fullmatch(r"(\S+) to (\S+)", part)
        if m:
            names.extend(_expand_range(m.group(1), m.group(2)) or _expand_open(*m.groups()))
        else:
            names.append(part)
    return names


def _is_tail(text: str) -> bool:
    """The rest of a quoted value wrapped mid-word (``INED"``, ``_HIGH"``)."""
    return bool(text) and text[0] != '"' and text.count('"') % 2 == 1


def _is_prose(text: str) -> bool:
    """Running description text rather than a value ("Sets the mode of ...")."""
    words = text.split()
    return len(words) >= 3 and sum(bool(re.fullmatch(r"[a-z][a-z,.()-]*", w)) for w in words) >= 2


_ONE_BIT_RANGE = re.compile(r"1'b0\s+to\s+1'b1")


def _split_values(text: str) -> list[str]:
    """Split an allowed-values cell into values. Whitespace just inside a quoted value
    (a wrapped cell joined as ``"GENERATE_X_ONLY ", ...``) is dropped, and the 1-bit
    range ``1'b0 to 1'b1`` becomes its two values, so each gets a coverage bin."""
    out: list[str] = []
    for v in re.split(r",|\s+or\s+", text):
        v = v.strip()
        if not v:
            continue
        if _ONE_BIT_RANGE.fullmatch(v):
            out += ["1'b0", "1'b1"]
            continue
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = f'"{v[1:-1].strip()}"'
        out.append(v)
    return out


def _closed(text: str) -> bool:
    """A value cell fragment that does not continue (quotes balanced, no trailing , / to)."""
    return text.count('"') % 2 == 0 and not text.endswith((",", " to"))


class _AttrTable:
    """One "Available Attributes" table: rows found by their type token (anchors)."""

    def __init__(self, block: list) -> None:
        self.block = block
        self.anchors: dict[int, re.Match] = {}
        self.barriers: list[int] = []
        self.headers: list[str] = []
        for i, ln in enumerate(block):
            if ln is _PAGEBREAK:
                self.barriers.append(i)
            elif "Attribute" in ln and "Type" in ln and "Default" in ln:
                self.barriers.append(i)
                self.headers.append(ln)
            elif (m := _ATTR_ANCHOR.match(ln.rstrip())) and m.start("type") <= _TYPE_MAX_COL:
                self.anchors[i] = m
            elif ln[:1].strip() and not _NAME_AT_START.match(ln):
                # full-width prose ("Programmable Inversion Attributes: ...")
                self.barriers.append(i)
        # A type cell wrapped as "3 significant" / "digit FLOAT": the row is centred
        # between the two lines, not on the line holding the type token.
        self.pos: dict[int, float] = {}
        for i, m in self.anchors.items():
            if _SIGNIFICANT.search(m.group(0)) or not re.search(
                r"digit\s+" + m.group("type"), m.group(0)
            ):
                continue
            for j in (i - 1, i - 2):
                if j >= 0 and block[j] is not _PAGEBREAK and _SIGNIFICANT.search(block[j]):
                    self.pos[i] = (i + j) / 2
                    break

    def parse(self) -> dict[str, dict]:
        if not self.anchors:
            return {}
        self._estimate_columns()
        chain_of, typeless = self._chain_names()
        cells = self._assign_values()
        attrs: dict[str, dict] = {}
        for i in sorted(self.anchors):
            if i not in chain_of:
                continue
            allowed = _join([t for _, t in cells[i]["A"]])
            default = _join([t for _, t in cells[i]["D"]])
            m = _DEFAULT_PHRASE.match(allowed)
            if m:
                allowed, default = m.group("allowed"), (default or m.group("default"))
            if not default:
                m = _TRAILING_DEFAULT.match(allowed)
                if m:
                    allowed, default = m.group("allowed"), m.group("default")
            entry = {
                "type": self.anchors[i].group("type"),
                "allowed": _split_values(allowed[:MAX_FRAGMENT]),
                "default": default[:MAX_FRAGMENT],
            }
            for name in _attr_names(_join_name([t for _, t in chain_of[i]])):
                attrs[name] = dict(entry, allowed=list(entry["allowed"]))
        for ch in typeless:
            for name in _attr_names(_join_name([t for _, t in ch])):
                attrs.setdefault(name, {"type": "", "allowed": [], "default": ""})
        return attrs

    # ---------------------------------------------------------------- columns

    def _estimate_columns(self) -> None:
        """Column starts for type (T), allowed values (A), default (D) and description
        (X) per page segment: T from the anchors, X from the most common indentation of
        prose, A and D from rows that fill all three value cells, else from the
        segment's repeated table header. ``d_edges`` collects every observed start of a
        default cell; merged runs are split there."""
        block, anchors = self.block, self.anchors
        self.seg_of: dict[int, int] = {}
        seg_header: dict[int, str] = {}
        seg = 0
        for i, ln in enumerate(block):
            if ln is _PAGEBREAK:
                seg += 1
            elif i in self.barriers and ln in self.headers:
                seg_header[seg] = ln
            self.seg_of[i] = seg
        self.d_edges: dict[int, set[int]] = {}

        def hdr_col(h: str | None, word: str) -> int | None:
            return h.index(word) if h and word in h else None

        def estimate(s: int) -> dict[str, float]:
            rows = [i for i in anchors if self.seg_of[i] == s]
            h = seg_header.get(s) or (self.headers[0] if self.headers else None)
            cols: dict[str, float] = {}
            t = [anchors[i].start("type") for i in rows]
            if not t and hdr_col(h, "Type") is not None:
                t = [hdr_col(h, "Type")]
            if t:
                cols["T"] = median(t)
            full = [_runs(anchors[i].group(0), anchors[i].end("cell")) for i in rows]
            full = [rs for rs in full if len(rs) >= 3]
            if full:
                cols["A"] = median(rs[0][0] for rs in full)
                cols["D"] = median(rs[1][0] for rs in full)
                self.d_edges.setdefault(s, set()).update(rs[1][0] for rs in full)
            else:
                for key, word in (("A", "Allowed"), ("D", "Default")):
                    if hdr_col(h, word) is not None:
                        cols[key] = hdr_col(h, word)
            floor = cols.get("A", (cols.get("T") or 0) + 10) + 4
            starts = Counter(
                rs[-1][0]
                for i, ln in enumerate(block)
                if self.seg_of[i] == s
                and ln is not _PAGEBREAK
                and i not in self.barriers
                and (rs := _runs(ln))
                and rs[-1][0] > floor
                and len(re.findall(r"\b[a-z]{2,}\b", rs[-1][1])) >= 2
            )
            if starts:
                cols["X"] = max(starts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            elif full:
                cols["X"] = median(rs[2][0] for rs in full)
            elif hdr_col(h, "Description") is not None:
                cols["X"] = hdr_col(h, "Description") - 12
            return cols

        table = estimate(self.seg_of[min(anchors)])
        self.cols = {s: {**table, **estimate(s)} for s in set(self.seg_of.values())}
        # standalone default-cell fragments also mark where merged runs must be split
        for i, ln in enumerate(block):
            if ln is _PAGEBREAK or i in self.barriers:
                continue
            for c, _ in _runs(ln)[1:]:
                if self._classify(c, self.seg_of[i]) == "D":
                    self.d_edges.setdefault(self.seg_of[i], set()).add(c)

    def _classify(self, col: int, s: int, keys: str = "TADX") -> str:
        cols = self.cols[s]
        return min((k for k in cols if k in keys), key=lambda k: (abs(cols[k] - col), k))

    def _split_run(self, c: int, text: str, s: int) -> list[tuple[int, str]]:
        """Split a run where a word starts on a later column (single-space merged cells),
        before running prose, or before the tail of a value wrapped mid-word."""
        cols = self.cols[s]
        edges = {v for k, v in cols.items() if k in "DX"} | self.d_edges.get(s, set())
        for m in re.finditer(r" (?=\S)", text):
            p = c + m.end()
            head, tail = text[: m.start()], text[m.end() :]
            at_edge = any(abs(p - v) <= 1 and v > c + 2 for v in edges)
            # never split inside a list ("14, 15, 16, 17, 18,")
            if (
                (at_edge and (not head.endswith(",") or re.fullmatch(r"[^,\s]+", tail)))
                or (not re.search("[a-z]", head) and _is_prose(tail))
                or (head.count('"') % 2 == 0 and _is_tail(tail.split()[0]))
            ):
                return [(c, head), *self._split_run(p, tail, s)]
        return [(c, text)]

    # ---------------------------------------------------------------- names

    def _chain_names(
        self,
    ) -> tuple[dict[int, list[tuple[int, str]]], list[list[tuple[int, str]]]]:
        """Chain column-0 name fragments that continue each other; give each chain to
        the anchor on one of its lines, else to the nearest free anchor."""
        anchors, barriers = self.anchors, self.barriers
        frags: list[tuple[int, str]] = []
        for i, ln in enumerate(self.block):
            if i in barriers or ln is _PAGEBREAK:
                continue
            if i in anchors:
                if anchors[i].group("name"):
                    frags.append((i, anchors[i].group("name")))
            elif ln[:1].strip() and (m := _NAME_AT_START.match(ln)):
                frags.append((i, m.group("name")))
        chains: list[list[tuple[int, str]]] = []
        for i, f in frags:
            if chains:
                pi, pf = chains[-1][-1]
                if not any(pi < b < i for b in barriers) and _continues(
                    pf, f, i - pi, pi in anchors
                ):
                    chains[-1].append((i, f))
                    continue
            chains.append([(i, f)])
        chain_of: dict[int, list[tuple[int, str]]] = {}
        loose = []
        for ch in chains:
            mine = [i for i, _ in ch if i in anchors and i not in chain_of]
            if mine:
                chain_of[mine[0]] = ch
            else:
                loose.append(ch)
        typeless = []
        for ch in loose:
            centre = (ch[0][0] + ch[-1][0]) / 2
            free = [
                a for a in anchors if a not in chain_of and abs(self.pos.get(a, a) - centre) <= 6
            ]
            a = _nearest(centre, free, barriers, lambda a: 0, self.pos)
            if a is None:
                typeless.append(ch)
            else:
                chain_of[a] = ch
        return chain_of, typeless

    # ---------------------------------------------------------------- values

    def _fragments(self) -> list[tuple[int, str, str, bool]]:
        """Every allowed (A) / default (D) fragment as (line, kind, text, on_anchor)."""
        out = []
        for i, ln in enumerate(self.block):
            if i in self.barriers or ln is _PAGEBREAK or not ln.strip():
                continue
            s = self.seg_of[i]
            if i in self.anchors:
                m = self.anchors[i]
                for c0, t0 in _runs(m.group(0), m.end("cell")):
                    for c, text in self._split_run(c0, t0, s):
                        k = self._classify(c, s, "ADX")
                        if k == "A" or (k == "D" and not _is_prose(text)):
                            out.append((i, k, text, True))
                continue
            for c0, t0 in _runs(ln):
                if c0 == 0:
                    # the rest of a name line ("REFCLK   1 significant 190-210, ...")
                    m = _NAME_AT_START.match(t0)
                    if not m:
                        continue
                    rest = t0[m.end() :]
                    c0, t0 = c0 + m.end() + len(rest) - len(rest.lstrip()), rest.strip()
                m = re.match(r"\d significant\s*", t0)
                if m:
                    c0, t0 = c0 + m.end(), t0[m.end() :]
                if not t0:
                    continue
                for c, text in self._split_run(c0, t0, s):
                    k = self._classify(c, s)
                    if k in "AD" and not (k == "D" and _is_prose(text)):
                        out.append((i, k, text, False))
        return out

    def _assign_values(self) -> dict[int, dict[str, list[tuple[int, str]]]]:
        """Give every value fragment to a row, in line order.

        1. A fragment on an anchor line belongs to that row. If it repeats a value
           already listed in the cell (``"MEMORY_QDR", "MEMORY"``), the repeat is the
           default merged in by a single space.
        2. A fragment continues a cell left open just above (unclosed quote, or a list
           ending in a comma).
        3. The tail of a quoted value (``_HIGH"``) whose start was merged into the
           allowed cell (``"CENTER_LOW", "CENTER``) turns that start into the default.
        4. A fragment ending in a comma starts a list that runs down through its row,
           so it goes to the nearest anchor at or up to 5 lines below it.
        5. Otherwise the nearest anchor, preferring rows without that cell; a cell
           complete on its anchor line cannot continue on the lines below.
        """
        anchors, barriers = self.anchors, self.barriers
        frags = self._fragments()
        cells = {i: {"A": [], "D": []} for i in anchors}
        own = {i: {k for j, k, _, on in frags if j == i and on} for i in anchors}

        def penalty(a: int, k: str, i: int) -> float:
            if k not in own[a]:
                return 0
            mine = [t for j, t in cells[a][k] if j == a]
            return 100 if i > a and mine and _closed(mine[-1]) else 1.5

        def clear(a: int, i: int) -> bool:
            return not any(min(a, i) < b < max(a, i) for b in barriers)

        fixed_default: set[int] = set()
        for i, k, text, on_anchor in frags:
            a = None
            if on_anchor:
                a = i
                seen = {v.strip('"') for v in _split_values(_join([t for _, t in cells[i]["A"]]))}
                m = re.fullmatch(r"(?:(.*,)\s+)?(\S+)", text)
                if k == "A" and m and m.group(2).strip('"') in seen:
                    if m.group(1):
                        cells[i]["A"].append((i, m.group(1)))
                    # anything already in D for this row was misread description text
                    cells[i]["D"] = [(i, m.group(2))]
                    fixed_default.add(i)
                    continue
            if a is None:
                open_cells = [
                    b
                    for b in anchors
                    if cells[b][k]
                    and 0 < i - cells[b][k][-1][0] <= 2
                    and clear(b, i)
                    and not _closed("".join(t for _, t in cells[b][k]))
                ]
                if open_cells:
                    a = max(open_cells, key=lambda b: cells[b][k][-1][0])
            if a is None and _is_tail(text) and k == "D":
                for b in anchors:
                    for n, (j, frag) in enumerate(cells[b]["A"]):
                        mm = re.fullmatch(r'(.*",)\s+("[^"\s]*)', frag)
                        if mm and 0 < i - j <= 3:
                            cells[b]["A"][n] = (j, mm.group(1))
                            cells[b]["D"].append((j, mm.group(2)))
                            a = b
                            break
                    if a is not None:
                        break
            if a is None and text.endswith(","):
                below = [b for b in anchors if i <= b <= i + 5 and clear(b, i)]
                if below:
                    a = min(below)
            if a is None:
                a = _nearest(
                    i,
                    list(anchors),
                    barriers,
                    lambda a, k=k: k not in own[a],
                    self.pos,
                    lambda a, k=k, i=i: penalty(a, k, i),
                )
            if a is not None and not (k == "D" and a in fixed_default):
                cells[a][k].append((i, text))
                cells[a][k].sort()
        return cells


def _parse_attributes(block: list) -> dict[str, dict]:
    return _AttrTable(block).parse()


# --------------------------------------------------------------------------- design entry

_DE_KEYS = {"instantiation": "instantiation", "inference": "inference"}


def _parse_design_entry(block: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in block:
        if ln is _PAGEBREAK:
            continue
        m = re.match(r"^(\S.*?)\s{2,}(\S.*?)\s*$", ln)
        if not m:
            continue
        key = m.group(1).strip().lower()
        if key.startswith("ip"):
            key = "ip_catalog"
        else:
            key = _DE_KEYS.get(key, re.sub(r"\W+", "_", key).strip("_"))
        out[key] = m.group(2)
    return out


# --------------------------------------------------------------------------- sections


def _section_bounds(lines: list[str]) -> list[int]:
    return [i for i in range(len(lines)) if _is_start(lines, i)]


def names_from_text(text: str) -> list[str]:
    """Every ``Primitive:`` section whose header has a PRIMITIVE_GROUP, in order."""
    lines = [ln.lstrip("\f").rstrip() for ln in text.split("\n")]
    out = []
    for i in _section_bounds(lines):
        if lines[i + 1].startswith("Primitive:") and any(
            "PRIMITIVE_GROUP:" in ln for ln in lines[i + 1 : i + 12]
        ):
            out.append(lines[i].strip())
    return out


def split_sections(text: str, names: list[str]) -> dict[str, DocSection]:
    lines = [ln.lstrip("\f").rstrip() for ln in text.split("\n")]
    pages = _page_numbers(lines)
    starts = _section_bounds(lines)
    wanted = set(names)
    out: dict[str, DocSection] = {}
    for n, i in enumerate(starts):
        name = lines[i].strip()
        if name not in wanted or not lines[i + 1].startswith("Primitive:"):
            continue
        head = lines[i + 1 : i + 12]
        if not any("PRIMITIVE_GROUP:" in ln for ln in head):
            continue
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        desc = lines[i + 1].split(":", 1)[1].strip()
        nxt = lines[i + 2]
        if nxt and not nxt[0].isspace() and ":" not in nxt:
            desc += ("" if desc.endswith("-") else " ") + nxt.strip()

        def grab(key: str, head: list[str] = head) -> str:
            for ln in head:
                m = re.search(rf"\b{key}:\s*(\S.*)$", ln)
                if m:
                    return m.group(1).strip()
            return ""

        blocks = _blocks(_clean(lines[i + 2 : end]))
        ports, review = _parse_ports(blocks.get("Port Descriptions", []))
        out[name] = DocSection(
            name=name,
            description=desc[:MAX_FRAGMENT],
            group=grab("PRIMITIVE_GROUP"),
            subgroup=grab("PRIMITIVE_SUBGROUP"),
            page=pages[i],
            ports=ports,
            attributes=_parse_attributes(blocks.get("Available Attributes", [])),
            design_entry=_parse_design_entry(blocks.get("Design Entry Method", [])),
            has_logic_table="Logic Table" in blocks,
            review=review,
        )
    return out
