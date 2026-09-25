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

The parser therefore finds anchor lines, assigns every other table line to the
nearest anchor, and classifies the text runs on those lines by column.

Only facts (names, widths, values) and short fragments (at most
``MAX_FRAGMENT`` characters) of AMD's text are kept.
"""

import re
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
    rf"^(?P<name>{_NAMEFRAG})?(?P<gap>\s+)(?:3 significant\s+)?(?:digit\s+)?"
    rf"(?P<type>{_TYPES})(?=\s|$)(?P<rest>.*)$"
)
_NAME_AT_START = re.compile(rf"^(?P<name>{_NAMEFRAG})(?=\s{{2,}}|$)")
_TYPE_MAX_COL = 45

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


def _nearest(idx: int, anchors: list[int], barriers: list[int], prefer, pos=None) -> int | None:
    """Index of the anchor nearest ``idx`` with no barrier in between.

    ``pos`` optionally maps an anchor to the (fractional) line its row is centred on.
    """
    best = None
    for a in anchors:
        lo, hi = sorted((a, idx))
        if any(lo < b < hi for b in barriers):
            continue
        d = abs((pos or {}).get(a, a) - idx)
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


def _parse_ports(block: list) -> dict[str, dict]:
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
    func_col = {i: m.start("func") for i, m in anchors.items() if m.group("func")}
    col = median(func_col.values()) if func_col else None
    first_desc: dict[int, tuple[int, str]] = {}
    for i, m in anchors.items():
        if m.group("func"):
            first_desc[i] = (i, m.group("func"))
    if col is not None:
        for i, ln in enumerate(block):
            if i in anchors or i in barriers or ln is _PAGEBREAK or not ln.strip():
                continue
            if abs((len(ln) - len(ln.lstrip())) - col) > 12:
                continue
            a = _nearest(i, list(anchors), barriers, lambda a: a not in func_col)
            if a is not None and (a not in first_desc or i < first_desc[a][0]):
                first_desc[a] = (i, ln.strip())
    ports: dict[str, dict] = {}
    for i, m in anchors.items():
        direction = _DIRECTIONS.get(m.group("dir"))
        if direction is None:
            continue  # e.g. "Internal" (other families only)
        width = int(m.group("width"))
        func = _fragment(first_desc[i][1]) if i in first_desc else ""
        for name, bus_w in _expand_names(m.group("name")):
            ports[name] = {"direction": direction, "width": bus_w or width, "function": func}
    return ports


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
    out = ""
    for f in frags:
        f = f.strip()
        if not out:
            out = f
        elif out.endswith("_") or f.startswith("_") or f.startswith('_"'):
            out += f
        elif out.endswith(",") or out.endswith(" to"):
            out += " " + f
        else:
            out += " " + f
    return out


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


def _attr_names(spec: str) -> list[str]:
    spec = spec.replace(" _", "_")
    names: list[str] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        m = re.fullmatch(r"(\S+) to (\S+)", part)
        if m:
            names.extend(_expand_range(m.group(1), m.group(2)) or [m.group(1), m.group(2)])
        else:
            names.append(part)
    return names


def _split_values(text: str) -> list[str]:
    return [v.strip() for v in text.split(",") if v.strip()]


def _parse_attributes(block: list) -> dict[str, dict]:
    anchors: dict[int, re.Match] = {}
    barriers: list[int] = []
    headers: list[str] = []
    for i, ln in enumerate(block):
        if ln is _PAGEBREAK:
            barriers.append(i)
            continue
        if "Attribute" in ln and "Type" in ln and "Default" in ln:
            barriers.append(i)
            headers.append(ln)
            continue
        m = _ATTR_ANCHOR.match(ln.rstrip())
        if m and m.start("type") <= _TYPE_MAX_COL:
            anchors[i] = m
        elif ln[:1].strip() and not _NAME_AT_START.match(ln):
            barriers.append(i)  # full-width prose ("Programmable Inversion Attributes: ...")
    if not anchors:
        return {}

    # A type cell wrapped as "3 significant" / "digit FLOAT": the row is centred
    # between the two lines, not on the line holding the type token.
    pos: dict[int, float] = {}
    for i, m in anchors.items():
        if "3 significant" in m.group(0) or not re.search(
            r"digit\s+" + m.group("type"), m.group(0)
        ):
            continue
        for j in (i - 1, i - 2):
            if j >= 0 and block[j] is not _PAGEBREAK and "3 significant" in block[j]:
                pos[i] = (i + j) / 2
                break

    # Column starts for (type, allowed, default, description), estimated per page
    # segment from anchor lines, falling back to the whole table and the header.
    seg_of: dict[int, int] = {}
    seg = 0
    for i, ln in enumerate(block):
        if ln is _PAGEBREAK:
            seg += 1
        seg_of[i] = seg

    def estimate(rows, wants=(3, 2)):
        t = [anchors[i].start("type") for i in rows]
        samples: dict[str, list[int]] = {"A": [], "D": [], "X": []}
        for want in wants:
            for i in rows:
                m = anchors[i]
                rs = _runs(m.group(0), m.end("type"))
                if len(rs) >= want:
                    for key, r in zip("ADX", rs, strict=False):
                        samples[key].append(r[0])
            if samples["A"] and samples["D"]:
                break
        cols = {"T": median(t)} if t else {}
        cols.update({k: median(v) for k, v in samples.items() if v})
        return cols

    table_cols = estimate(list(anchors))
    if headers and ("D" not in table_cols or "X" not in table_cols):
        h = headers[0]
        for key, word in (("A", "Allowed"), ("D", "Default"), ("X", "Description")):
            if key not in table_cols and word in h:
                table_cols[key] = h.index(word) - 4
    seg_cols = {}
    for s in set(seg_of[i] for i in anchors):
        rows = [i for i in anchors if seg_of[i] == s]
        c = estimate(rows, wants=(3,))
        seg_cols[s] = {**table_cols, **c} if {"A", "D", "X"} <= set(c) else table_cols

    def classify(col: int, cols: dict) -> str:
        return min(cols, key=lambda k: (abs(cols[k] - col), k))

    cells: dict[int, dict[str, list[tuple[int, str]]]] = {
        i: {"N": [], "A": [], "D": []} for i in anchors
    }
    own: dict[int, set[str]] = {}
    for i, m in anchors.items():
        cols = seg_cols[seg_of[i]]
        if m.group("name"):
            cells[i]["N"].append((i, m.group("name")))
        for c, text in _runs(m.group(0), m.end("type")):
            k = classify(c, cols)
            if k in "AD":
                cells[i][k].append((i, text))
        own[i] = {k for k, v in cells[i].items() if v}

    for i, ln in enumerate(block):
        if i in anchors or i in barriers or ln is _PAGEBREAK or not ln.strip():
            continue
        runs = _runs(ln)
        for c, text in runs:
            if c == 0:
                nm = _NAME_AT_START.match(text) or re.match(rf"^{_NAMEFRAG}", text)
                if not nm:
                    continue
                k, text = "N", nm.group(0)
            else:
                cols = seg_cols.get(seg_of[i], table_cols)
                k = classify(c, cols)
                if k not in "AD":
                    continue
            a = _nearest(i, list(anchors), barriers, lambda a, k=k: k not in own[a], pos)
            if a is not None:
                cells[a][k].append((i, text))

    attrs: dict[str, dict] = {}
    for i in sorted(anchors):
        c = cells[i]
        if not c["N"]:
            continue
        spec = _join_name([t for _, t in sorted(c["N"])])
        allowed = _join([t for _, t in sorted(c["A"])])
        default = _join([t for _, t in sorted(c["D"])])
        m = _DEFAULT_PHRASE.match(allowed)
        if m:
            allowed, default = m.group("allowed"), (default or m.group("default"))
        if not default:
            m = _TRAILING_DEFAULT.match(allowed)
            if m:
                allowed, default = m.group("allowed"), m.group("default")
        entry = {
            "type": anchors[i].group("type"),
            "allowed": _split_values(allowed[:MAX_FRAGMENT]),
            "default": default[:MAX_FRAGMENT],
        }
        for name in _attr_names(spec):
            attrs[name] = dict(entry, allowed=list(entry["allowed"]))
    return attrs


# --------------------------------------------------------------------------- design entry

_DE_KEYS = {"instantiation": "instantiation", "inference": "inference"}


def _parse_design_entry(block: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in block:
        if ln is _PAGEBREAK:
            continue
        m = re.match(r"^(\S.*?)\s{2,}(\S.*?)\s*$", ln)
        if not m:
            if out and not ln.strip():
                continue
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
            desc += " " + nxt.strip()

        def grab(key, head=head):
            for ln in head:
                m = re.search(rf"\b{key}:\s*(\S.*)$", ln)
                if m:
                    return m.group(1).strip()
            return ""

        blocks = _blocks(_clean(lines[i + 2 : end]))
        out[name] = DocSection(
            name=name,
            description=desc[:MAX_FRAGMENT],
            group=grab("PRIMITIVE_GROUP"),
            subgroup=grab("PRIMITIVE_SUBGROUP"),
            page=pages[i],
            ports=_parse_ports(blocks.get("Port Descriptions", [])),
            attributes=_parse_attributes(blocks.get("Available Attributes", [])),
            design_entry=_parse_design_entry(blocks.get("Design Entry Method", [])),
            has_logic_table="Logic Table" in blocks,
        )
    return out
