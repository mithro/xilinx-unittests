# Step 1 — Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the project's foundation:

- the `xut` Python tool;
- the machine-readable catalog of all 103 UG953 primitives;
- work-unit ownership;
- status generation (PROGRESS/TODO/LOG);
- lint;
- doctor;
- contributor/agent rules;
- CI.

After this, parallel work units can start.

**Architecture:** `xut` is a Python package in `tools/xut/` with a `click` CLI. The catalog merges two sources:

- **UNISIM Verilog module headers**, parsed with `pyslang`. These are authoritative for port and parameter names, directions, widths and defaults.
- **UG953 text**, produced with `pdftotext -layout`. It is authoritative for group/subgroup, description, allowed values, design-entry method and page.

Each generated catalog file has a hand-maintained `.overrides.yaml` layered on top. Status files are per primitive; the aggregate markdown is generated only on `main`.

**Tech Stack:**

- Python ≥ 3.12, managed with `uv`
- click, PyYAML, jsonschema, pyslang 11.x, requests
- pytest and ruff
- poppler `pdftotext` (host binary)
- GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md` (rev 2). Read §§3, 9, 10, 11, 12, 13, 15.

## Global Constraints

- License is Apache-2.0. Every source file (`.py .v .sv .yaml .sh .tcl .toml`, workflows) starts with an `SPDX-License-Identifier: Apache-2.0` comment line. Markdown files are exempt.
- AMD PDFs and AMD prose are never committed. The catalog stores facts (names, widths, values, page numbers) and short paraphrases only.
- Generated files `status/PROGRESS.md`, `status/TODO.md`, `status/LOG.md` and `status/PORTABILITY.md` are never committed on branches. Only the orchestrator commits them on `main`, as `status: regenerate`.
- Commit subjects are prefixed `<area>: ` (e.g. `infra: `, `catalog: `, `docs: `, `flops: `). Make small commits after every change.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Never use `2>/dev/null`. Capture long command output to a log file, then inspect the log file.
- Vivado is only ever sourced in a subshell: `bash -c 'source /opt/xilinx/Vivado/2025.2/settings64.sh && ...'`.
- UNISIM source directory: `/opt/xilinx/Vivado/2025.2/data/verilog/src/unisims`. CI fallback: `third_party/XilinxUnisimLibrary/verilog/src/unisims`.
- UG953 pinned edition: **2026.1**, docs.amd.com map id `i4rliuWFec9CVaGVE8DYrg`.
- The branch for this plan is `infra/bootstrap`, in a worktree at `../xilinx-unittests-worktrees/infra-bootstrap`. Open one PR at the end of each task group, as marked.

## Review Focus

1. **Primitives missing from the UNISIM directory.** BUFGCE_1, BUFGMUX, BUFGMUX_1, BUFGMUX_CTRL, RAM32X1S_1, RAM32X2S, RAM64X1S_1 and ROM{32,64,128,256}X1 live only in `data/verilog/src/retarget/`. The extractor must look there, record `model_library: retarget`, and never crash or silently drop a primitive. Pinned by a test in Task 4.
2. **String parameters.** pyslang renders these as hex literals (e.g. `56'h44454641554c54`). A user expects `IOSTANDARD: "DEFAULT"`. Pinned in Task 3.
3. **`localparam`s and `XIL_TIMING`-only parameters (LOC, MSGON, XON)** must not appear as attributes. Pinned in Task 3.
4. **UG953 text wraps table cells across lines.** A port or attribute that exists in UNISIM but is not found in the UG953 table, or vice versa, must be reported in `EXTRACTION_REPORT.md`, not dropped. Pinned in Task 4.
5. **Running `xut status` on a branch** must refuse to write the generated files unless `--force` is given or the current branch is `main`. This prevents the conflicts spec §11 forbids. Pinned in Task 7.

---

## File Structure

```
pyproject.toml                        project + tool config (ruff, pytest)
tools/xut/__init__.py                 version
tools/xut/cli.py                      click group: xut {fetch-docs,catalog,status,lint,doctor}
tools/xut/paths.py                    repo-root discovery + well-known paths
tools/xut/docs_fetch.py               download UG953 PDF + templates zip into .cache/docs
tools/xut/catalog/__init__.py
tools/xut/catalog/unisim.py           pyslang-based module header parser
tools/xut/catalog/ug953.py            UG953 text section splitter + table parsers
tools/xut/catalog/build.py            merge unisim + ug953 → CatalogEntry, write YAML + report
tools/xut/catalog/model.py            CatalogEntry/Port/Attribute dataclasses, load w/ overrides
tools/xut/catalog/portclass.py        default port-class heuristics (spec §5.1)
tools/xut/workunits.py                load/validate docs/work-units.yaml, path ownership
tools/xut/status.py                   status schema, load, generate PROGRESS/TODO/LOG
tools/xut/lint.py                     SPDX, work-unit path ownership, test.yaml doc checks
tools/xut/doctor.py                   preflight checks
tools/xut/schemas/status.schema.json
tools/xut/schemas/catalog.schema.json
tools/xut/schemas/test.schema.json
tools/tests/…                         pytest tests for the tool (NOT primitive tests)
tools/tests/fixtures/…                small UG953 text excerpts written by us, UNISIM-like .v files
tools/hooks/commit-msg                commit prefix enforcement
AGENTS.md                             rules for all agents/contributors
docs/work-units.yaml
docs/review/code-quality.md           reviewer prompt (a)
docs/review/correctness.md            reviewer prompt (b)
docs/templates/primitive-README.md
docs/templates/test.yaml
catalog/7series/<PRIM>.yaml           generated (103 files)
catalog/EXTRACTION_REPORT.md          generated
status/7series/<PRIM>.yaml            initial stubs (103 files)
.github/workflows/ci.yml
third_party/XilinxUnisimLibrary       submodule
```

The test fixtures are **hand-written imitations** of the UG953 layout. They are not copies of AMD text.

---

### Task 1: Python project skeleton, CLI and CI

**Files:**
- Create: `pyproject.toml`, `tools/xut/__init__.py`, `tools/xut/cli.py`, `tools/xut/paths.py`, `tools/tests/test_cli.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `xut.paths.repo_root() -> pathlib.Path`, which walks up from cwd until it finds `pyproject.toml` containing `name = "xilinx-unittests"`.
  - The `xut.cli.main` click group.
  - The console script `xut`.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd /home/tim/github/f4pga/xilinx-unittests
git worktree add ../xilinx-unittests-worktrees/infra-bootstrap -b infra/bootstrap
cd ../xilinx-unittests-worktrees/infra-bootstrap
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
# SPDX-License-Identifier: Apache-2.0
[project]
name = "xilinx-unittests"
version = "0.1.0"
description = "Cross-checked test suite for Xilinx FPGA primitives"
license = "Apache-2.0"
requires-python = ">=3.12"
dependencies = [
  "click>=8.1",
  "PyYAML>=6.0",
  "jsonschema>=4.21",
  "pyslang>=11,<12",
  "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[project.scripts]
xut = "xut.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["tools/xut"]

[tool.pytest.ini_options]
testpaths = ["tools/tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]
```

- [ ] **Step 3: Write the failing test** at `tools/tests/test_cli.py`

```python
# SPDX-License-Identifier: Apache-2.0
from click.testing import CliRunner

from xut import __version__
from xut.cli import main
from xut.paths import repo_root


def test_version_option():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_repo_root_contains_pyproject():
    assert (repo_root() / "pyproject.toml").is_file()
```

- [ ] **Step 4: Run it and confirm it fails**

Run: `uv venv && uv pip install -e '.[dev]' > .cache/uv-install.log 2>&1; uv run pytest tools/tests/test_cli.py -v`

Expected: FAIL (`ModuleNotFoundError: xut`). Create `.cache/` first with `mkdir -p .cache`.

- [ ] **Step 5: Implement**

`tools/xut/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""xut — Xilinx UnitTests tooling."""

__version__ = "0.1.0"
```

`tools/xut/paths.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Repository path discovery."""

from pathlib import Path

_MARKER = 'name = "xilinx-unittests"'


def repo_root(start: Path | None = None) -> Path:
    """Return the repository root (directory holding our pyproject.toml)."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        pp = d / "pyproject.toml"
        if pp.is_file() and _MARKER in pp.read_text():
            return d
    raise FileNotFoundError(f"not inside xilinx-unittests (searched up from {here})")


def cache_dir() -> Path:
    return repo_root() / ".cache"


VIVADO_UNISIM = Path("/opt/xilinx/Vivado/2025.2/data/verilog/src/unisims")
VIVADO_RETARGET = Path("/opt/xilinx/Vivado/2025.2/data/verilog/src/retarget")


def submodule_unisim() -> Path:
    return repo_root() / "third_party/XilinxUnisimLibrary/verilog/src/unisims"
```

`tools/xut/cli.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point."""

import click

from xut import __version__


@click.group()
@click.version_option(__version__, prog_name="xut")
def main() -> None:
    """Xilinx primitive test-suite tooling."""
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `uv run pytest tools/tests -v > .cache/pytest.log 2>&1; tail -5 .cache/pytest.log`

Expected: `2 passed`.

- [ ] **Step 7: Add CI** at `.github/workflows/ci.yml`

```yaml
# SPDX-License-Identifier: Apache-2.0
name: ci
on: [push, pull_request]
jobs:
  tooling:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with: {submodules: true}
      - uses: astral-sh/setup-uv@v3
      - run: sudo apt-get update && sudo apt-get install -y poppler-utils
      - run: uv venv && uv pip install -e '.[dev]'
      - run: uv run ruff check tools
      - run: uv run ruff format --check tools
      - run: uv run pytest -v
      - run: uv run xut lint
```

The `xut lint` step fails until Task 8. Mark that step `continue-on-error: true` now, and remove the flag in Task 8.

- [ ] **Step 8: Run ruff and commit**

```bash
uv run ruff format tools && uv run ruff check tools
git add pyproject.toml tools .github
git commit -m "infra: add xut python package skeleton, CLI and CI"
```

---

### Task 2: UG953 fetcher

**Files:**
- Create: `tools/xut/docs_fetch.py`, `tools/tests/test_docs_fetch.py`
- Modify: `tools/xut/cli.py`

**Interfaces:**
- Consumes: `xut.paths.cache_dir()`
- Produces:
  - `xut.docs_fetch.DocSpec` (frozen dataclass: `name, edition, map_id`)
  - `xut.docs_fetch.UG953`, the pinned 2026.1 `DocSpec`
  - `fetch(spec: DocSpec, dest_dir: Path, session=None, local: Path | None = None) -> Path`, which returns the path to the PDF
  - `pdf_to_text(pdf: Path) -> Path`, which returns the path of the `-layout` text
  - CLI `xut fetch-docs [--local PATH]`

The docs.amd.com khub API, as verified during research:

- `GET https://docs.amd.com/api/khub/maps/{map_id}/attachments` returns a JSON list of `{id, filename, mimeType, ...}`.
- `GET https://docs.amd.com/api/khub/maps/{map_id}/attachments/{id}/content` returns the bytes.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.docs_fetch import UG953, DocSpec, fetch


class FakeResp:
    def __init__(self, *, json_data=None, content=b"", status=200):
        self._j, self.content, self.status_code = json_data, content, status

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, listing, pdf_bytes):
        self.listing, self.pdf, self.calls = listing, pdf_bytes, []

    def get(self, url, timeout):
        self.calls.append(url)
        if url.endswith("/attachments"):
            return FakeResp(json_data=self.listing)
        return FakeResp(content=self.pdf)


def test_fetch_picks_pdf_attachment(tmp_path):
    listing = [
        {"id": "zip1", "filename": "templates.zip", "mimeType": "application/zip"},
        {"id": "pdf1", "filename": "ug953.pdf", "mimeType": "application/pdf"},
    ]
    s = FakeSession(listing, b"%PDF-1.7 fake")
    out = fetch(UG953, tmp_path, session=s)
    assert out.read_bytes().startswith(b"%PDF")
    assert s.calls[-1].endswith("/attachments/pdf1/content")


def test_fetch_is_cached(tmp_path):
    s = FakeSession([{"id": "p", "filename": "a.pdf", "mimeType": "application/pdf"}], b"%PDF-x")
    fetch(UG953, tmp_path, session=s)
    n = len(s.calls)
    fetch(UG953, tmp_path, session=s)
    assert len(s.calls) == n


def test_fetch_rejects_non_pdf(tmp_path):
    s = FakeSession([{"id": "p", "filename": "a.pdf", "mimeType": "application/pdf"}], b"<html>")
    with pytest.raises(ValueError, match="not a PDF"):
        fetch(UG953, tmp_path, session=s)


def test_local_copy_used(tmp_path):
    src = tmp_path / "given.pdf"
    src.write_bytes(b"%PDF-local")
    out = fetch(UG953, tmp_path / "d", local=src)
    assert out.read_bytes() == b"%PDF-local"


def test_docspec_filename():
    assert DocSpec("ug953", "2026.1", "x").pdf_name == "ug953-2026.1.pdf"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest tools/tests/test_docs_fetch.py -v`

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `tools/xut/docs_fetch.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Download AMD libraries guides into the local cache (never committed)."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

API = "https://docs.amd.com/api/khub/maps"


@dataclass(frozen=True)
class DocSpec:
    name: str
    edition: str
    map_id: str

    @property
    def pdf_name(self) -> str:
        return f"{self.name}-{self.edition}.pdf"


UG953 = DocSpec("ug953", "2026.1", "i4rliuWFec9CVaGVE8DYrg")


def fetch(spec: DocSpec, dest_dir: Path, session=None, local: Path | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / spec.pdf_name
    if local is not None:
        shutil.copyfile(local, out)
        return out
    if out.is_file():
        return out
    s = session or requests.Session()
    r = s.get(f"{API}/{spec.map_id}/attachments", timeout=60)
    r.raise_for_status()
    pdfs = [a for a in r.json() if a.get("mimeType") == "application/pdf"]
    if len(pdfs) != 1:
        raise ValueError(f"expected exactly one PDF attachment for {spec}, got {pdfs}")
    r = s.get(f"{API}/{spec.map_id}/attachments/{pdfs[0]['id']}/content", timeout=300)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError(f"downloaded content for {spec} is not a PDF")
    out.write_bytes(r.content)
    return out


def pdf_to_text(pdf: Path) -> Path:
    txt = pdf.with_suffix(".txt")
    if not txt.is_file():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)
    return txt
```

Add the CLI command in `tools/xut/cli.py`:

```python
@main.command("fetch-docs")
@click.option("--local", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def fetch_docs_cmd(local: Path | None) -> None:
    """Download UG953 into .cache/docs (or copy a local PDF there)."""
    from xut.docs_fetch import UG953, fetch, pdf_to_text
    from xut.paths import cache_dir

    pdf = fetch(UG953, cache_dir() / "docs", local=local)
    click.echo(f"pdf:  {pdf}\ntext: {pdf_to_text(pdf)}")
```

Also add `from pathlib import Path` to the imports.

- [ ] **Step 4: Run the tests, then fetch for real**

```bash
uv run pytest tools/tests/test_docs_fetch.py -v
uv run xut fetch-docs > .cache/fetch.log 2>&1; cat .cache/fetch.log
```

Expected: 5 passed. The real fetch prints a PDF path and a text path, and the PDF is about 6.4 MB.

- [ ] **Step 5: Commit**

```bash
git add tools && git commit -m "infra: add UG953 fetcher (docs.amd.com khub API, cached, never committed)"
```

---

### Task 3: UNISIM module header parser

**Files:**
- Create: `tools/xut/catalog/__init__.py`, `tools/xut/catalog/unisim.py`, `tools/tests/test_unisim.py`, `tools/tests/fixtures/unisim/TOYANSI.v`, `tools/tests/fixtures/unisim/TOYOLD.v`

**Interfaces:**
- Produces:
  - `xut.catalog.unisim.HdlPort` (frozen: `name: str, direction: str  # "input"|"output"|"inout", width: int`)
  - `xut.catalog.unisim.HdlParam` (frozen: `name: str, kind: str  # "string"|"integer"|"real"|"bits", width: int | None, default: str | int | float`)
  - `xut.catalog.unisim.HdlModule` (`name, ports: list[HdlPort], params: list[HdlParam], source: Path`)
  - `parse_module(path: Path, name: str) -> HdlModule`
  - `find_model(name: str, search: list[Path]) -> tuple[Path, str] | None`, which returns `(file, library_dir_name)`

Rules:

- `localparam`s are excluded.
- Parameters defined only under `ifdef XIL_TIMING` are excluded automatically, because no defines are passed to the preprocessor.
- String parameters are decoded to Python `str`.
- Bit-vector defaults are rendered as Verilog literals (`"1'b0"`, `"256'h0"`).

- [ ] **Step 1: Write the fixtures** (our own toy modules, not UNISIM copies)

`tools/tests/fixtures/unisim/TOYANSI.v`:

```verilog
// SPDX-License-Identifier: Apache-2.0
`timescale 1 ps / 1 ps
module TOYANSI #(
  `ifdef XIL_TIMING
  parameter LOC = "UNPLACED",
  `endif
  parameter [0:0] INIT = 1'b1,
  parameter IOSTANDARD = "DEFAULT",
  parameter integer DEPTH = 4,
  parameter real PERIOD = 10.0
)(
  output Q,
  input [3:0] D,
  inout IO
);
  localparam HIDDEN = 3;
  assign Q = D[0];
endmodule
```

`tools/tests/fixtures/unisim/TOYOLD.v`:

```verilog
// SPDX-License-Identifier: Apache-2.0
`timescale 1 ps / 1 ps
module TOYOLD (DO, ADDR, CLK);
  parameter integer DOA_REG = 0;
  parameter [255:0] INIT_00 = 256'h0;
  output [15:0] DO;
  input [13:0] ADDR;
  input CLK;
  assign DO = 16'h0;
endmodule
```

- [ ] **Step 2: Write the failing tests**

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.catalog.unisim import HdlParam, HdlPort, find_model, parse_module
from xut.paths import VIVADO_UNISIM

FIX = Path(__file__).parent / "fixtures" / "unisim"


def test_ansi_ports():
    m = parse_module(FIX / "TOYANSI.v", "TOYANSI")
    assert m.ports == [
        HdlPort("Q", "output", 1),
        HdlPort("D", "input", 4),
        HdlPort("IO", "inout", 1),
    ]


def test_params_decoded_and_filtered():
    m = parse_module(FIX / "TOYANSI.v", "TOYANSI")
    by = {p.name: p for p in m.params}
    assert set(by) == {"INIT", "IOSTANDARD", "DEPTH", "PERIOD"}  # no LOC, no HIDDEN
    assert by["IOSTANDARD"] == HdlParam("IOSTANDARD", "string", None, "DEFAULT")
    assert by["INIT"] == HdlParam("INIT", "bits", 1, "1'b1")
    assert by["DEPTH"].kind == "integer" and by["DEPTH"].default == 4
    assert by["PERIOD"].kind == "real" and by["PERIOD"].default == 10.0


def test_non_ansi():
    m = parse_module(FIX / "TOYOLD.v", "TOYOLD")
    assert [p.width for p in m.ports] == [16, 14, 1]
    assert {p.name: p.default for p in m.params}["INIT_00"] == "256'h0"


def test_find_model_prefers_first_dir(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "X.v").write_text("module X; endmodule\n")
    assert find_model("X", [tmp_path / "a", tmp_path / "b"]) == (tmp_path / "b" / "X.v", "b")
    assert find_model("Y", [tmp_path / "a"]) is None


@pytest.mark.skipif(not VIVADO_UNISIM.is_dir(), reason="Vivado not installed")
def test_real_iobuf_strings():
    m = parse_module(VIVADO_UNISIM / "IOBUF.v", "IOBUF")
    assert {p.name: p.default for p in m.params}["IOSTANDARD"] == "DEFAULT"
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tools/tests/test_unisim.py -v`

Expected: ImportError.

- [ ] **Step 4: Implement `tools/xut/catalog/unisim.py`**

```python
# SPDX-License-Identifier: Apache-2.0
"""Extract port/parameter interface of a UNISIM model with pyslang."""

from dataclasses import dataclass, field
from pathlib import Path

import pyslang

_DIR = {"In": "input", "Out": "output", "InOut": "inout"}


@dataclass(frozen=True)
class HdlPort:
    name: str
    direction: str
    width: int


@dataclass(frozen=True)
class HdlParam:
    name: str
    kind: str
    width: int | None
    default: str | int | float


@dataclass
class HdlModule:
    name: str
    source: Path
    ports: list[HdlPort] = field(default_factory=list)
    params: list[HdlParam] = field(default_factory=list)


def _param(p) -> HdlParam:
    decl_type = p.type
    cv = p.value
    if decl_type.isString or (cv.isString() if hasattr(cv, "isString") else False):
        return HdlParam(p.name, "string", None, cv.convertToStr().str() if hasattr(cv.convertToStr(), "str") else _hex_to_str(str(cv)))
    if decl_type.isFloating:
        return HdlParam(p.name, "real", None, float(str(cv)))
    if str(decl_type) in ("integer", "int"):
        return HdlParam(p.name, "integer", None, int(str(cv).split("'")[-1].lstrip("sdhb"), 10) if "'" in str(cv) else int(str(cv)))
    return HdlParam(p.name, "bits", decl_type.bitWidth, str(cv))


def _hex_to_str(lit: str) -> str:
    """Decode a Verilog hex literal like 56'h44454641554c54 into ASCII."""
    digits = lit.split("'h", 1)[1]
    return bytes.fromhex(digits.rjust(len(digits) + len(digits) % 2, "0")).decode("ascii")


def parse_module(path: Path, name: str) -> HdlModule:
    tree = pyslang.syntax.SyntaxTree.fromFile(str(path))
    comp = pyslang.ast.Compilation()
    comp.addSyntaxTree(tree)
    inst = next(i for i in comp.getRoot().topInstances if i.name == name)
    body = inst.body
    mod = HdlModule(name=name, source=path)
    for p in body.portList:
        mod.ports.append(HdlPort(p.name, _DIR[str(p.direction).split(".")[-1]], p.type.bitWidth))
    for p in body.parameters:
        if getattr(p, "isLocalParam", False) or not getattr(p, "isPortParam", True):
            continue
        mod.params.append(_param(p))
    return mod


def find_model(name: str, search: list[Path]) -> tuple[Path, str] | None:
    for d in search:
        f = d / f"{name}.v"
        if f.is_file():
            return f, d.name
    return None
```

**Implementer note.** The exact pyslang attribute names (`isString`, `isFloating`, `isLocalParam`, `isPortParam`, `convertToStr`) must be checked against pyslang 11. First print `dir(p)`, `dir(p.type)` and `dir(p.value)` for the TOYANSI parameters. Then keep the *behaviour* the tests pin, and simplify `_param` to whatever the real API supports. A body-level `parameter` in a non-ANSI module (TOYOLD) **is** a real parameter and must be kept. Only `localparam` is excluded.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tools/tests/test_unisim.py -v`

Expected: all pass. The Vivado test runs on the host.

- [ ] **Step 6: Commit**

```bash
git add tools && git commit -m "catalog: add pyslang-based UNISIM header parser"
```

---

### Task 4: UG953 section parser and catalog builder

**Files:**
- Create: `tools/xut/catalog/ug953.py`, `tools/xut/catalog/model.py`, `tools/xut/catalog/portclass.py`, `tools/xut/catalog/build.py`, `tools/xut/schemas/catalog.schema.json`, `tools/tests/test_ug953.py`, `tools/tests/test_build.py`, `tools/tests/fixtures/ug953_toy.txt`
- Modify: `tools/xut/cli.py`

**Interfaces:**
- Consumes: `parse_module` and `find_model` (Task 3); `UG953` and `pdf_to_text` (Task 2)
- Produces:
  - `xut.catalog.ug953.DocSection` with fields:
    - `name`, `description`, `group`, `subgroup`, `page: int`
    - `ports: dict[str, dict]` of `{direction, width, function}`
    - `attributes: dict[str, dict]` of `{type, allowed, default}`
    - `design_entry: dict[str, str]`
    - `has_logic_table: bool`
  - `split_sections(text: str, names: list[str]) -> dict[str, DocSection]`
  - `xut.catalog.model.CatalogEntry` (dataclass) with fields:
    - `name, family, group, subgroup, description, doc: {guide, edition, page}`
    - `model: {library, file}`
    - `ports: list[{name, direction, width, cls, doc_function}]`
    - `attributes: list[{name, kind, width, default, allowed, doc_type}]`
    - `design_entry`
    - `claims: list[{id, text, page, provenance}]`
    - `status_undocumented: bool`
  - `load_entry(family: str, name: str, root: Path) -> CatalogEntry`, which applies overrides
  - `xut.catalog.portclass.default_class(prim: str, port: str, direction: str) -> str`
  - `xut.catalog.build.build_all(text_path: Path, names: list[str], out_dir: Path, search: list[Path]) -> list[str]`, which returns the report lines
  - CLI `xut catalog build`

**Parsing strategy.**

- A section starts at a column-0 line equal to the primitive name, followed by a line `Primitive: <description>`. `PRIMITIVE_GROUP:` and `PRIMITIVE_SUBGROUP:` appear within the next 10 lines. The section ends at the next section start.
- The page number is the last `UG953 v2026.1 <page>` footer seen before the section start, plus 1 if the start comes after the footer.
- **Port table rows:** a column-0 token matching `^[A-Z][A-Z0-9_\[\]:]*` followed by `Input|Output|Inout` and a width (an integer, or `<n>` from `[n-1:0]`), all within the Port Descriptions block.
- **Attribute rows:** a column-0 token followed by one of `BINARY|HEX|DECIMAL|STRING|FLOAT|INTEGER|BOOLEAN|1'b[01]` and so on, within the Available Attributes block. Take the first column group as the type, the next as allowed values (split on `,`), and the next as the default.
- Continuation lines are ignored. Descriptions are not needed beyond the first fragment, and nothing longer than 120 characters from AMD's text is stored.
- **Design entry:** the three lines under `Design Entry Method`.

**Port classes** (spec §5.1), assigned by `default_class` and overridable:

- `clock`: names in `{C, CLK, CLKARDCLK, CLKBWRCLK, RDCLK, WRCLK, CLKIN1, CLKIN2, CLKFBIN, CLKDIV, CLKB, OCLK, OCLKB, CLKDIVP, DCLK, REFCLK, C0, C1, I0, I1 (BUFGCTRL/BUFGMUX only), I (BUF*/BUFG* only), WCLK}`
- `async`: `{CLR, PRE, RST (FIFO*/MMCM/PLL/ISERDES/OSERDES), S0, S1, CE0, CE1, IGNORE0, IGNORE1 (BUFGCTRL), PWRDWN, GSR, GTS}`
- `gate`: `G` on LDCE/LDPE
- `inout`: any `inout`
- `pad`: `I` on IBUF*, `O`/`OB` on OBUF*, and `I`/`IB` on IBUFDS*
- `drp`: `{DADDR, DI, DO, DEN, DWE, DRDY}` on MMCM/PLL/XADC
- `clock_out`: outputs named `CLKOUT*`, `CLKFBOUT*`, `O` on BUF*/BUFG*, `LOCKED` is **not** a clock_out (it is `data`)
- `data`: everything else

- [ ] **Step 1: Write the fixture** `tools/tests/fixtures/ug953_toy.txt`

This is a synthetic imitation of the layout, written by us:

```
UG953 v2026.1                                                     10
June 23, 2026
TOYFF
Primitive: Toy flip-flop for parser tests

    PRIMITIVE_GROUP: REGISTER
    PRIMITIVE_SUBGROUP: SDR

Introduction
Toy text.

Port Descriptions

              Port                Direction            Width                  Function
C                                 Input           1              Clock input.
D                                 Input           1              Data input
Q                                 Output          1              Data output
DO[15:0]                          Output          16             Wide output


Design Entry Method
Instantiation                                                         Yes
Inference                                                             Recommended
IP and IP Integrator Catalog                                          No


Available Attributes

         Attribute         Type           Allowed Values        Default          Description
INIT                       BINARY         1'b0, 1'b1           1'b0             Initial value
MODE                       STRING         "FAST", "SLOW"       "FAST"           Toy mode
                                                                                wrapped line
UG953 v2026.1                                                     11
June 23, 2026
TOYLUT
Primitive: Toy LUT

    PRIMITIVE_GROUP: CLB
    PRIMITIVE_SUBGROUP: LUT

Port Descriptions

              Port                Direction            Width                  Function
I0                                Input           1              Input
O                                 Output          1              Output
```

- [ ] **Step 2: Write the failing tests**

`tools/tests/test_ug953.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from xut.catalog.ug953 import split_sections

TXT = (Path(__file__).parent / "fixtures" / "ug953_toy.txt").read_text()


def test_sections_found_with_group_and_page():
    s = split_sections(TXT, ["TOYFF", "TOYLUT"])
    assert s["TOYFF"].group == "REGISTER" and s["TOYFF"].subgroup == "SDR"
    assert s["TOYFF"].page == 10
    assert s["TOYLUT"].page == 11
    assert s["TOYFF"].description == "Toy flip-flop for parser tests"


def test_ports_parsed_including_bus():
    p = split_sections(TXT, ["TOYFF"])["TOYFF"].ports
    assert p["C"] == {"direction": "input", "width": 1, "function": "Clock input."}
    assert p["DO"]["width"] == 16


def test_attributes_parsed():
    a = split_sections(TXT, ["TOYFF"])["TOYFF"].attributes
    assert a["INIT"] == {"type": "BINARY", "allowed": ["1'b0", "1'b1"], "default": "1'b0"}
    assert a["MODE"]["allowed"] == ['"FAST"', '"SLOW"']


def test_design_entry():
    d = split_sections(TXT, ["TOYFF"])["TOYFF"].design_entry
    assert d == {"instantiation": "Yes", "inference": "Recommended", "ip_catalog": "No"}


def test_missing_section_is_absent_not_error():
    assert "NOPE" not in split_sections(TXT, ["NOPE"])
```

`tools/tests/test_build.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import yaml

from xut.catalog.build import build_all
from xut.catalog.model import load_entry
from xut.catalog.portclass import default_class

FIX = Path(__file__).parent / "fixtures"


def _toy_models(tmp_path):
    u = tmp_path / "unisims"
    u.mkdir()
    (u / "TOYFF.v").write_text(
        "module TOYFF #(parameter [0:0] INIT = 1'b0, parameter MODE = \"FAST\", "
        "parameter [0:0] EXTRA = 1'b0)(output Q, input C, input D, output [15:0] DO);\n"
        "endmodule\n"
    )
    r = tmp_path / "retarget"
    r.mkdir()
    (r / "TOYLUT.v").write_text("module TOYLUT(output O, input I0); endmodule\n")
    return [u, r]


def test_build_writes_yaml_and_reports_mismatch(tmp_path):
    out = tmp_path / "catalog"
    report = build_all(FIX / "ug953_toy.txt", ["TOYFF", "TOYLUT", "GHOST"], out,
                       _toy_models(tmp_path))
    ff = yaml.safe_load((out / "TOYFF.yaml").read_text())
    assert ff["group"] == "REGISTER"
    assert [p["name"] for p in ff["ports"]] == ["Q", "C", "D", "DO"]
    assert {a["name"]: a["default"] for a in ff["attributes"]}["MODE"] == "FAST"
    # EXTRA is in UNISIM but not in UG953 table -> reported, still present
    assert any("TOYFF" in line and "EXTRA" in line for line in report)
    lut = yaml.safe_load((out / "TOYLUT.yaml").read_text())
    assert lut["model"]["library"] == "retarget"
    # GHOST: documented name with no model and no section -> reported, not crash
    assert any("GHOST" in line for line in report)


def test_overrides_merge(tmp_path):
    out = tmp_path / "catalog" / "7series"
    build_all(FIX / "ug953_toy.txt", ["TOYFF"], out, _toy_models(tmp_path))
    (out / "TOYFF.overrides.yaml").write_text(yaml.safe_dump({
        "ports": {"D": {"cls": "async"}},
        "claims": [{"id": "TOYFF.C1", "text": "Q follows D", "page": 10,
                    "provenance": "doc:10"}],
    }))
    e = load_entry("7series", "TOYFF", tmp_path)
    assert {p["name"]: p["cls"] for p in e.ports}["D"] == "async"
    assert e.claims[0]["id"] == "TOYFF.C1"


def test_default_port_classes():
    assert default_class("FDRE", "C", "input") == "clock"
    assert default_class("FDCE", "CLR", "input") == "async"
    assert default_class("LDCE", "G", "input") == "gate"
    assert default_class("IOBUF", "IO", "inout") == "inout"
    assert default_class("MMCME2_ADV", "CLKOUT0", "output") == "clock_out"
    assert default_class("MMCME2_ADV", "LOCKED", "output") == "data"
    assert default_class("MMCME2_ADV", "DADDR", "input") == "drp"
    assert default_class("FDRE", "D", "input") == "data"
    assert default_class("IBUF", "I", "input") == "pad"
    assert default_class("BUFGCTRL", "I0", "input") == "clock"
    assert default_class("LUT2", "I0", "input") == "data"
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `uv run pytest tools/tests/test_ug953.py tools/tests/test_build.py -v`

- [ ] **Step 4: Implement `ug953.py`, `portclass.py`, `model.py`, `build.py`**

`model.py`: the `CatalogEntry` dataclass, and `load_entry`, which reads `<root>/catalog/<family>/<name>.yaml` and deep-merges `<name>.overrides.yaml`. Merge rules:

- `ports` and `attributes` in the overrides are **dicts keyed by name**, whose fields update the matching list entries.
- `claims` in the overrides **replace** the generated list (the generated list is always empty).
- Any other top-level scalar key replaces the generated value.

Validate the merged result against `tools/xut/schemas/catalog.schema.json`, where `cls` is enum `[clock, async, gate, data, inout, clock_out, pad, drp]`.

`build.py`: for each name:

1. `find_model(name, search)` gives the model. `library` is the search dir's name (`unisims` or `retarget`), or `none`.
2. Parse the section with `split_sections`.
3. Ports come from HDL if there is a model, otherwise from the doc table.
4. `cls` comes from `default_class`.
5. Attributes come from HDL params. `allowed` and `doc_type` come from the doc table when present.
6. Every name that appears in only one of UNISIM or UG953 gets a report line: `"<PRIM>: port|attribute <X> only in unisim|ug953"`.
7. Missing section or missing model also get a report line.
8. Write the YAML with an SPDX header comment and `# GENERATED by xut catalog build — edit <PRIM>.overrides.yaml instead`.

Return the report lines.

CLI `xut catalog build`:

- names come from the "Design Elements" list in the UG953 TOC. Use `names_from_text(text)`, which finds every `Primitive:` header whose next ~10 lines contain `PRIMITIVE_GROUP` (research found exactly 103; assert `len == 103` and fail loudly otherwise);
- search `[VIVADO_UNISIM, VIVADO_RETARGET]`, falling back to `[submodule_unisim()]` if Vivado is absent;
- output to `catalog/7series/`;
- write the report to `catalog/EXTRACTION_REPORT.md`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tools/tests -v > .cache/pytest.log 2>&1; tail -15 .cache/pytest.log`

Expected: all pass.

- [ ] **Step 6: Commit the code**

```bash
git add tools && git commit -m "catalog: UG953 section parser, port classes, catalog builder with overrides"
```

- [ ] **Step 7: Generate the real catalog, then inspect it**

```bash
uv run xut catalog build > .cache/catalog-build.log 2>&1; tail -20 .cache/catalog-build.log
ls catalog/7series/*.yaml | wc -l                 # expect 103
grep -c "only in" catalog/EXTRACTION_REPORT.md
```

Spot-check `FDRE.yaml`: ports Q, C, CE, D, R; attributes INIT, IS_C_INVERTED, IS_D_INVERTED, IS_R_INVERTED; group REGISTER; page ≈ 375. Also spot-check `RAMB36E1.yaml`, `MMCME2_ADV.yaml` and `IOBUF.yaml`.

If there are more than ~40 "only in" mismatches, the parser is wrong, not the doc. Fix the parser with an added fixture test and re-run.

- [ ] **Step 8: Commit the generated catalog**

```bash
git add catalog && git commit -m "catalog: generate 7-series catalog for all 103 UG953 primitives"
```

**PR checkpoint A:** push the branch and open PR "infra: bootstrap part A — xut skeleton, fetcher, catalog", then run the review gate from spec §13.4.

---

### Task 5: Contributor rules, work units, review prompts, templates, commit hook

**Files:**
- Create: `AGENTS.md`, `docs/work-units.yaml`, `tools/xut/workunits.py`, `tools/tests/test_workunits.py`, `docs/review/code-quality.md`, `docs/review/correctness.md`, `docs/templates/primitive-README.md`, `docs/templates/test.yaml`, `tools/hooks/commit-msg`, `tools/tests/test_commit_hook.py`

**Interfaces:**
- Produces:
  - `xut.workunits.WorkUnit` (frozen: `name, family, primitives: tuple[str, ...], group_dirs: tuple[str, ...]`)
  - `load_units(root: Path) -> dict[str, WorkUnit]`
  - `owned_paths(unit: WorkUnit) -> list[str]`, a list of glob patterns
  - `unit_for_branch(branch: str) -> str | None`: for `unit/7series/flops` it returns `flops`
  - `INFRA_PATHS: list[str]`

- [ ] **Step 1: Write `docs/work-units.yaml`**

It must contain every one of the 103 primitives exactly once:

```yaml
# SPDX-License-Identifier: Apache-2.0
family: 7series
units:
  flops:        {group: register, primitives: [FDCE, FDPE, FDRE, FDSE]}
  latches:      {group: register, primitives: [LDCE, LDPE]}
  ddr_regs:     {group: register, primitives: [IDDR, IDDR_2CLK, ODDR]}
  luts:         {group: clb, primitives: [LUT1, LUT2, LUT3, LUT4, LUT5, LUT6, LUT6_2, CFGLUT5]}
  muxf:         {group: clb, primitives: [MUXF7, MUXF8]}
  carry:        {group: clb, primitives: [CARRY4]}
  lutram:       {group: clb, primitives: [RAM128X1D, RAM128X1S, RAM256X1S, RAM32M, RAM32X1D, RAM32X1S, RAM32X1S_1, RAM32X2S, RAM64M, RAM64X1D, RAM64X1S, RAM64X1S_1]}
  rom:          {group: clb, primitives: [ROM32X1, ROM64X1, ROM128X1, ROM256X1]}
  srl:          {group: clb, primitives: [SRL16E, SRLC32E]}
  bram:         {group: blockram, primitives: [RAMB18E1, RAMB36E1]}
  bram_fifo:    {group: blockram, primitives: [FIFO18E1, FIFO36E1]}
  dsp:          {group: arithmetic, primitives: [DSP48E1]}
  bufg:         {group: clock, primitives: [BUFG, BUFGCE, BUFGCE_1, BUFGCTRL, BUFGMUX, BUFGMUX_1, BUFGMUX_CTRL]}
  regional_clk: {group: clock, primitives: [BUFH, BUFHCE, BUFIO, BUFMR, BUFMRCE, BUFR]}
  mmcm_pll:     {group: clock, primitives: [MMCME2_ADV, MMCME2_BASE, PLLE2_ADV, PLLE2_BASE]}
  config_jtag:  {group: configuration, primitives: [BSCANE2, CAPTUREE2]}
  config_id:    {group: configuration, primitives: [DNA_PORT, EFUSE_USR, USR_ACCESSE2]}
  config_icap:  {group: configuration, primitives: [ICAPE2, FRAME_ECCE2, STARTUPE2]}
  ibuf:         {group: io, primitives: [IBUF, IBUFDS, IBUFDS_DIFF_OUT, IBUFDS_DIFF_OUT_IBUFDISABLE, IBUFDS_DIFF_OUT_INTERMDISABLE, IBUFDS_IBUFDISABLE, IBUFDS_INTERMDISABLE, IBUF_IBUFDISABLE, IBUF_INTERMDISABLE]}
  obuf:         {group: io, primitives: [OBUF, OBUFDS, OBUFT, OBUFTDS]}
  iobuf:        {group: io, primitives: [IOBUF, IOBUFDS, IOBUFDS_DCIEN, IOBUFDS_DIFF_OUT, IOBUFDS_DIFF_OUT_DCIEN, IOBUFDS_DIFF_OUT_INTERMDISABLE, IOBUFDS_INTERMDISABLE, IOBUF_DCIEN, IOBUF_INTERMDISABLE]}
  weak_drivers: {group: io, primitives: [KEEPER, PULLDOWN, PULLUP]}
  dci:          {group: io, primitives: [DCIRESET]}
  delay:        {group: io, primitives: [IDELAYCTRL, IDELAYE2, ODELAYE2]}
  serdes:       {group: io, primitives: [ISERDESE2, OSERDESE2]}
  phy_fifo:     {group: io, primitives: [IN_FIFO, OUT_FIFO]}
  xadc:         {group: advanced, primitives: [XADC]}
  gt_buf:       {group: advanced, primitives: [IBUFDS_GTE2]}
```

- [ ] **Step 2: Write the failing tests** `tools/tests/test_workunits.py`

```python
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from xut.paths import repo_root
from xut.workunits import load_units, owned_paths, unit_for_branch


def test_every_catalog_primitive_in_exactly_one_unit():
    root = repo_root()
    units = load_units(root)
    listed = [p for u in units.values() for p in u.primitives]
    assert len(listed) == len(set(listed)), "primitive listed twice"
    catalog = {f.stem for f in (root / "catalog/7series").glob("*.yaml")
               if not f.name.endswith(".overrides.yaml")}
    assert set(listed) == catalog


def test_owned_paths_for_flops():
    u = load_units(repo_root())["flops"]
    paths = owned_paths(u)
    assert "tests/7series/register/FDRE/**" in paths
    assert "catalog/7series/FDRE.overrides.yaml" in paths
    assert "models/xut_models/7series/_common/flops.py" in paths
    assert "status/7series/FDRE.yaml" in paths
    assert "findings/FDRE-*.md" in paths
    assert "catalog/7series/FDRE.yaml" not in paths  # generated = infra only


@pytest.mark.parametrize("branch,unit", [
    ("unit/7series/flops", "flops"), ("infra/bootstrap", None), ("main", None)])
def test_unit_for_branch(branch, unit):
    assert unit_for_branch(branch) == unit


def test_duplicate_primitive_rejected(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/work-units.yaml").write_text(
        "family: 7series\nunits:\n  a: {group: x, primitives: [P]}\n  b: {group: x, primitives: [P]}\n")
    with pytest.raises(ValueError, match="P"):
        load_units(tmp_path)
```

- [ ] **Step 3: Implement `tools/xut/workunits.py`**

`owned_paths(u)` returns, for each primitive `P` of unit `u`:

- `tests/<family>/<group>/<P>/**`
- `catalog/<family>/<P>.overrides.yaml`
- `models/xut_models/<family>/<p_lower>.py`
- `status/<family>/<P>.yaml`
- `findings/<P>-*.md`

plus these per-unit paths:

- `models/xut_models/<family>/_common/<unit>.py`
- `log/*-unit-<family>-<unit>-*.md`

`INFRA_PATHS` = everything else. `load_units` raises `ValueError` naming any primitive listed twice.

- [ ] **Step 4: Write `AGENTS.md`**

AGENTS.md must contain these sections, with concrete commands:

1. **Read first:** the spec and the current plan.
2. **One branch per work unit, in its own worktree.** Show the exact `git worktree add ../xilinx-unittests-worktrees/<branch-with-dashes> -b <branch>` command, and the branch types from spec §13.2.
3. **Only touch owned paths.** Run `uv run xut lint --branch` before every push.
4. **Small commits** after every change, including logs and status. Prefix `<unit|area>: `. Install the hook with `git config core.hooksPath tools/hooks`.
5. **Never commit** `status/PROGRESS.md`, `TODO.md`, `LOG.md` or `PORTABILITY.md`, and never AMD PDFs or AMD text.
6. **Progress log.** Add `log/<YYYY-MM-DDTHHMM>-<branch-slug>-<slug>.md` for every session. Say what changed, test results and next steps.
7. **Status.** Update `status/<family>/<PRIM>.yaml` whenever a result changes.
8. **Clean-room golden models.** Write them from UG953 only; never open UNISIM source while writing a model. Tag every behaviour `doc:<page>` or `inferred:<reason>`.
9. **Never weaken a test to hide a divergence.** Write `findings/<PRIM>-<slug>.md` instead.
10. **Shell rules.** No `2>/dev/null`. Log to files, then inspect them. Source Vivado only in a subshell.
11. **SPDX header** on every source file.
12. **Review.** Every PR gets two reviewer agents, using `docs/review/*.md`. Address must-fix findings in new commits.
13. **Infra dependencies.** Record a TODO in your log entry, or stack on the `infra/*` branch. Never edit infra paths from a unit branch.

- [ ] **Step 5: Write the reviewer prompts**

`docs/review/code-quality.md` and `docs/review/correctness.md` are self-contained prompts. Each tells the reviewer to:

- read AGENTS.md and the spec sections relevant to it;
- `gh pr diff <N>`;
- check its list.

The lists:

- **(a) Code quality:**
  - Python style (ruff-clean, typed, small functions);
  - HDL portability to xsim, Icarus and Verilator;
  - blocking vs non-blocking assignment misuse;
  - races at time 0 and at GSR release;
  - hard-coded paths;
  - silent excepts and skips;
  - SPDX headers;
  - commit hygiene.
- **(b) Correctness:**
  - every claim and attribute value checked against UG953 (the reviewer runs `uv run xut fetch-docs` and reads the section);
  - golden-model provenance tags, and that the clean-room rule was followed;
  - coverage bins vs the catalog;
  - README completeness (purpose, why, gaps, related);
  - declared unsupported runners justified.

Output format: `gh pr review <N> --comment --body-file <file>`, with each finding prefixed **[must-fix]** or **[nit]**, and a final line `VERDICT: approve` or `VERDICT: changes-requested`.

- [ ] **Step 6: Write the templates**

`docs/templates/primitive-README.md` has the sections from spec §12 as headings, each with a one-line instruction in an HTML comment.

`docs/templates/test.yaml` is exactly the spec §11 example, with `FDRE` replaced by `<PRIM>`.

- [ ] **Step 7: Write the commit-msg hook and its test**

`tools/hooks/commit-msg`:

```bash
#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Enforce "<area>: subject" commit subjects (spec §13.3).
subject=$(head -n1 "$1")
if [[ "$subject" =~ ^(Merge|Revert|fixup!|squash!) ]]; then exit 0; fi
if [[ ! "$subject" =~ ^[a-z0-9_./-]+:\ .+ ]]; then
  echo "commit-msg: subject must look like '<area>: <summary>' (got: $subject)" >&2
  exit 1
fi
```

`tools/tests/test_commit_hook.py` runs the hook via `subprocess` against temp files and checks:

- `flops: add X` → exit 0
- `Add stuff` → exit 1
- `Merge branch x` → exit 0

- [ ] **Step 8: Run the tests, then commit in small pieces**

```bash
chmod +x tools/hooks/commit-msg
uv run pytest tools/tests -v > .cache/pytest.log 2>&1; tail -5 .cache/pytest.log
git add docs/work-units.yaml tools/xut/workunits.py tools/tests/test_workunits.py && git commit -m "infra: add work-unit ownership map and loader"
git add AGENTS.md && git commit -m "docs: add AGENTS.md contributor and agent rules"
git add docs/review && git commit -m "docs: add reviewer prompts for code quality and correctness"
git add docs/templates && git commit -m "docs: add primitive README and test.yaml templates"
git add tools/hooks tools/tests/test_commit_hook.py && git commit -m "infra: add commit-msg prefix hook"
```

---

### Task 6: Status schema and initial status stubs

**Files:**
- Create: `tools/xut/schemas/status.schema.json`, `tools/xut/schemas/test.schema.json`, `tools/xut/status.py` (schema and load only, in this task), `tools/tests/test_status_schema.py`, `status/7series/<PRIM>.yaml` × 103

**Interfaces:**
- Produces:
  - `xut.status.RESULT_VALUES = ("pass", "fail", "error", "skip", "not-run", "unsupported", "n/a")`
  - `load_status(path: Path) -> dict` (validated)
  - `new_stub(entry: CatalogEntry, unit: str) -> dict`
  - `coverage_bins(entry: CatalogEntry) -> list[str]`: bins are `port:<P>`, `attr:<A>=<v>` for every allowed enumerated value, `attr:<A>` for non-enumerated attributes, and `claim:<id>`

Status file shape:

```yaml
# SPDX-License-Identifier: Apache-2.0
primitive: FDRE
family: 7series
work_unit: flops
model_library: unisims
measured:
  tree_hash: null
  tools: {}
results: {}            # "<level>/<runner>/<flow>": pass|fail|...
findings: []
coverage:
  covered: []
  uncovered: [port:C, port:CE, port:D, port:Q, port:R, "attr:INIT=1'b0", ...]
notes: ""
```

- [ ] **Step 1: Write the failing tests**

- A stub for FDRE validates against the schema.
- Its `uncovered` list contains `port:R` and `attr:INIT=1'b1`.
- `results` keys must match `^L[0-3]/[a-z]+/[a-z0-9-]+$`, and a bad key fails validation.
- A value outside `RESULT_VALUES` fails validation.

- [ ] **Step 2: Implement.** Add a CLI command `xut status init`. It writes a stub for every catalog entry that has no status file yet, and never overwrites an existing one.

- [ ] **Step 3: Run the tests, run `uv run xut status init`, and check that `ls status/7series | wc -l` is 103**

- [ ] **Step 4: Commit**

```bash
git add tools && git commit -m "infra: add status schema, loader and stub generator"
git add status/7series && git commit -m "status: add initial status stubs for all 103 7-series primitives"
```

---

### Task 7: `xut status` report generation (PROGRESS / TODO / LOG)

**Files:**
- Modify: `tools/xut/status.py`, `tools/xut/cli.py`
- Create: `tools/tests/test_status_report.py`

**Interfaces:**
- Produces:
  - `render_progress(statuses: list[dict], units: dict) -> str`
  - `render_todo(statuses, entries) -> str`
  - `render_log(log_dir: Path) -> str`
  - CLI `xut status generate [--force]`, which refuses unless on `main` or `--force` is given

**PROGRESS.md layout:**

- A header with the generation time and git HEAD.
- A summary table per group: number of primitives, and for each level the count with any `pass`.
- A per-primitive table, one row per primitive. The columns are:
  - Unit
  - L0, L1, L2 and L3, each showing a compact runner mark string. Runners are in the order `python xsim iverilog verilator hw`. Marks are `✓` pass, `✗` fail, `!` error, `–` not-run, `∅` unsupported, and `·` n/a. Where one runner has several flows, fail beats error beats pass.
  - Coverage `%`, as covered/(covered+uncovered).
  - Findings count.

**TODO.md:** per unit, then per primitive, list the uncovered bins, the unsupported cells with their reasons, and the open findings.

**LOG.md:** a list of every `log/*.md`, sorted by filename (the timestamp prefix), showing the first heading line and a link.

- [ ] **Step 1: Write the failing tests**

- `render_progress` of two fake statuses (FDRE with `L1/iverilog/rtl: pass` and `L1/hw/vivado: fail`; FDSE empty) gives an FDRE row whose L1 cell contains `✓` and `✗`, and an FDSE row that is all `–`.
- The coverage percentage is computed correctly: 2 covered out of 8 is `25%`.
- `render_log` over a tmp dir with two entries lists them in timestamp order.
- Running the `generate` CLI on a non-main branch without `--force` exits non-zero with a message mentioning `main`. Mock the branch detection function `current_branch()`.

- [ ] **Step 2: Implement. Run the tests.**

- [ ] **Step 3: Commit** with `infra: add status report generation (PROGRESS/TODO/LOG)`.

---

### Task 8: `xut lint`

**Files:**
- Create: `tools/xut/lint.py`, `tools/tests/test_lint.py`
- Modify: `tools/xut/cli.py`, `.github/workflows/ci.yml` (remove `continue-on-error`)

**Interfaces:**
- Produces:
  - `LintIssue` (frozen: `path: str, rule: str, message: str, severity: str  # "error"|"warning"`)
  - `check_spdx(root, files) -> list[LintIssue]`
  - `check_branch_paths(branch, changed_files, units) -> list[LintIssue]`
  - `check_generated_not_committed(changed_files, branch) -> list[LintIssue]`
  - `check_tests_documented(root) -> list[LintIssue]`
  - `check_status_files(root) -> list[LintIssue]`
  - CLI `xut lint [--branch]`. `--branch` uses `git diff --name-only origin/main...HEAD`.

Rules:

- **`spdx`:** every tracked `*.py *.v *.sv *.yaml *.yml *.sh *.tcl *.toml` and `tools/hooks/*` must have `SPDX-License-Identifier: Apache-2.0` in its first 3 lines. Excluded: `third_party/**` and `catalog/EXTRACTION_REPORT.md`.
- **`branch-paths`:**
  - on `unit/*` branches, every changed file must match `owned_paths(unit)` or be `log/*-unit-*.md`;
  - on `integ/<name>` branches, only `tests/7series/integration/<name>/**` and log files;
  - on `docs/*` branches, only `docs/**` and log files;
  - `infra/*` branches may touch anything except other units' owned paths. Catalog generated files, status stubs and templates *are* allowed on infra branches.
- **`generated-files`:** the four generated status files must not be changed on any branch other than `main`.
- **`tests-documented`:** for each `tests/**/test.yaml`, every test id must appear in the sibling README.md, and `related:` ids that don't exist produce a **warning**.
- **`status-schema`:** every `status/**/*.yaml` must validate.

- [ ] **Step 1: Write failing tests for each rule.** Use tmp repos built with `git init` in `tmp_path`, plus unit-level function tests. Include:
  - a `unit/7series/flops` branch touching `tools/xut/cli.py` → error;
  - the same branch touching `tests/7series/register/FDRE/README.md` → OK;
  - the same branch touching `status/PROGRESS.md` → error;
  - a `.py` file without SPDX → error;
  - a `related:` id that doesn't exist → warning only, and the exit code is still 0.

- [ ] **Step 2: Implement. Run the tests. Run `uv run xut lint` on the repo and fix any real issues it finds.**

- [ ] **Step 3: Commit** with `infra: add xut lint (spdx, branch ownership, generated files, docs, status schema)`, and commit the CI change separately.

---

### Task 9: `xut doctor` and the UNISIM submodule

**Files:**
- Create: `tools/xut/doctor.py`, `tools/tests/test_doctor.py`, `.gitmodules` (via `git submodule add`)
- Modify: `tools/xut/cli.py`

**Interfaces:**
- Produces:
  - `Check` (frozen: `name, ok: bool, detail: str, enables: tuple[str, ...]`)
  - `run_checks(probe=None) -> list[Check]`, where `probe` is injectable for tests
  - CLI `xut doctor`. It prints a table, then the "available runners" list. It always exits 0; it is informational.

Checks:

| Check | Enables |
|---|---|
| `vivado`: `/opt/xilinx/Vivado/2025.2/settings64.sh` exists | xsim, vivado |
| `docker`: `docker info` succeeds | iverilog, verilator, cocotb, yosys, nextpnr-xilinx, vpr (once containers exist) |
| `gh`: `gh auth status` exit 0 | nothing (process) |
| `submodule`: `third_party/XilinxUnisimLibrary/verilog/src/unisims/FDRE.v` exists | CI UNISIM |
| `docs`: `.cache/docs/ug953-2026.1.pdf` exists, or the docs.amd.com API responds with HTTP 200 | catalog |
| `pdftotext` is on PATH | catalog |
| `fpgas.online`: `ssh -o BatchMode=yes -o ConnectTimeout=10 -p 10222 pi@ps1.fpgas.online true` | hw |

The ssh port and host come from `hw/boards/fpgas_online.yaml` once it exists. Until then they are a constant in `doctor.py` with a comment pointing at that future file.

- [ ] **Step 1: Add the submodule**

```bash
git submodule add https://github.com/Xilinx/XilinxUnisimLibrary third_party/XilinxUnisimLibrary
git -C third_party/XilinxUnisimLibrary log --oneline -1
git commit -m "infra: add XilinxUnisimLibrary as submodule (Vivado 2020.1 models)"
```

- [ ] **Step 2: Write failing tests** using a fake `probe` that returns canned results. Check that a missing Vivado removes `xsim` from the available runners, and that every check's `detail` is non-empty.

- [ ] **Step 3: Implement. Run the tests. Run `uv run xut doctor > .cache/doctor.log 2>&1` and inspect the log.**

- [ ] **Step 4: Commit** with `infra: add xut doctor preflight checks`.

**PR checkpoint B:** push the branch and open PR "infra: bootstrap part B — work units, rules, status, lint, doctor". Run the review gate. After merge, on `main`:

```bash
uv run xut status generate > .cache/status-gen.log 2>&1
git add status/PROGRESS.md status/TODO.md status/LOG.md
git commit -m "status: regenerate"
```

---

## Self-review against the spec (performed while writing this plan)

- §3 sources and extraction method, with its report: Tasks 2–4.
- Behavioural claims: the catalog schema has `claims` and the overrides carry them (Task 4). Populating claims is per work unit (steps 2 and 5, not step 1).
- §9 coverage bins: Task 6.
- §10 layout and ownership: Task 5 (work-units, owned paths).
- §10 SPDX: Tasks 1 and 8.
- §11 status, tree hash, generated files only on main: Tasks 6–7.
- §12 README template and lint: Tasks 5 and 8.
- §13 worktrees, branch types, path lint, commit hook, review prompts: Tasks 5 and 8.
- §15 doctor: Task 9.
- CI: Task 1.
- Explicitly **not** in step 1 (these belong to step-2 and later plans):
  - wrapper, vector formats and runners (§§5–6), containers (§12);
  - crosscheck (§8), the portability table (§6);
  - the hardware harness (§7);
  - `hw/boards/fpgas_online.yaml`.
