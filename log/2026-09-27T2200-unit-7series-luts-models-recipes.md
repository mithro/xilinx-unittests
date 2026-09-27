# unit/7series/luts — golden models, recipes, generator and guards (Tasks B2, B3)

Tasks B2 and B3 of the unit playbook, transcribed from the reviewed plan (rulings S52, S53,
S55, S55a). The intake and claims (Task B1) are in `2026-09-27T2155-unit-7series-luts-claims.md`.

## What changed

- **B2, golden models** (clean room: UG953 v2026.1 only, no UNISIM file opened):
  `models/xut_models/7series/_common/luts.py` (`Lut`, `DualLut`, `CfgLut5`) and the eight
  primitive modules `lut1.py` … `lut6_2.py`, `cfglut5.py`. The model tests
  (`tests/7series/clb/_shared/luts/test_luts_models.py`) were run red first (100 failures,
  every one `LookupError: no golden model`), then green.
- **B3**: `luts_recipes.py` completed, `luts_tests.py` (file generator and the mutant
  table, built on `xut.unitkit`), `test_luts_tests.py` (`UnitGuards` plus the unit's own
  checks), and the generated files: per primitive `test.yaml`, `README.md`,
  `vectors/gen.py`, the cocotb module, and for LUT1-LUT6/LUT6_2 the two sv wrappers.
  88 tests: LUT1 9, LUT2 9, LUT3-LUT6 10 each, LUT6_2 12, CFGLUT5 18.

### Deviation from the plan

The B2 commit carries only the top part of `luts_recipes.py` (above `class LutDriver`), as
the plan says. In that partial file `Callable`, `Iterable`, `functools.partial` and the
`GenContext` type import are unused, so `ruff check` failed on it (F401). The B2 commit
drops those four imports; the B3 commit restores the file verbatim from the plan.

## Test results

- `pytest tests/7series/clb/_shared/luts/test_luts_models.py`: 100 passed (at the B2 commit).
- `pytest tests/7series/clb/_shared/luts`: 167 passed in 27 s (100 model tests,
  56 `UnitGuards` cases, 11 unit checks).
- `ruff check .` and `ruff format --check models tests`: clean.
- `xut lint`: 0 errors, 14 warnings, all the expected `portability-agreement` ones
  (decision D12): `L0.illegal_init` and `L1.sv_x_inputs` of LUT1-LUT6 and LUT6_2 declare
  `verilator: "unsupported"` for an x attribute or an x stimulus. CFGLUT5 raises none.
- `xut run 'unit:luts' --runner python --jobs 16` (heavy lock, 16G scope): exit 0;
  64 vector tests pass, 24 sv/cocotb tests skip with their declared reasons (16 `SV_PY`,
  8 `CO_PY`). The `L1.gsr_transparent` (7) and `L1.gsr_after_reconfig` (2) stimuli are
  `hw_renderable no` (the §7.2 GSR reason); the others checked are `hw_renderable yes`.
  `xut vec check` on `CFGLUT5.L1.edge_polarity/cfg-clk1_ones` and
  `LUT6_2.L1.doc_example/cfg-or6_or5` reports no error.

## Next steps

- Task B4: the shared sv bodies `luts_x_tb.svh` / `luts_gsr_tb.svh` that the generated
  wrappers include, and CFGLUT5's hand-written sv testbenches.
- Task B5: the cocotb session `luts_cocotb.py` that the generated cocotb modules import.
- Task B6: the simulator runs and crosscheck; fill in the two CFGLUT5 doc-gap findings.
