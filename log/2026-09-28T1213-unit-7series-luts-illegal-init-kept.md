# luts B6: keep L0.illegal_init as a known doc-gap

## What changed

- **Eight new open findings**, `findings/<PRIM>-doc-gap-L0-illegal_init.md`, one each
  for LUT1-LUT6, LUT6_2 and CFGLUT5:
  - UG953 lists the legal INIT values (the HEX value on each primitive's attribute page)
    but promises no runtime rejection;
  - UNISIM accepts an all-x INIT: unisim-2025.2 on xsim and iverilog, unisim-gh-2020.1
    on iverilog.
- **Each `L0.illegal_init` lists its finding in `expected_divergence`** (`cls: doc-gap`,
  `runners: [xsim, iverilog]`) and names it in `gaps`. `luts_tests.py`'s `add()` gained
  an `expected` argument for this.
- **The test and its expected outcome (reject) are unchanged.** The READMEs link the
  findings through the generator.
- **Deviation:** this departs from the playbook's Task A6/D8 reject-test rule (remove the
  test and add an L0.smoke gap) by the user's decision of 2026-09-28. The flops unit
  removed its INIT=1'bx reject tests earlier, under that rule.
- **The Verilator V3Gate findings** (`LUT{4,5,6,6_2}-sim-divergence-verilator-constant-output`)
  stay open. No `config_exclusions` were added, per the orchestrator's ruling: infra
  fixes this on `infra/verilator-gate`.

## Results

- `pytest tests/7series/clb`: 167 passed.
- `xut lint --branch`: 0 errors and the 18 known D12 warnings.
- `xut crosscheck LUT1` (on the earlier results) still reports L0.illegal_init as
  `incomplete`, with "expected_divergence ... matched no disagreement". Crosscheck
  classifies trace disagreements, and a reject test's acceptance is a result `fail`
  without one. So the entry cannot turn it into a `known-divergence`.
  - **TODO (infra):** have crosscheck map an "expected rejection, got acceptance" fail
    to a listed finding. Until then this test keeps crosscheck at exit 4.

## Next steps

Wait for the orchestrator's go, once the Verilator fix merges. Then:

1. Rebase.
2. Re-run both model sources at low priority (`nice -n 19 ionice -c2 -n7`).
3. Crosscheck.
4. `xut status record` for both sources.
5. Write the results log and open the B7 PR.
