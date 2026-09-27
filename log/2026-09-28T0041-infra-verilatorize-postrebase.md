# infra/verilatorize: fixes after the rebase onto main (2ea5d98)

## What changed
- `tools/tests/test_runner_verilator.py`: main moved the `_shared/<unit>` lookup into
  `TestCase.shared_dirs` and removed `test_runner_cocotb._shared_dirs`. The verilator tests
  imported that helper and monkeypatched `shared_dirs`; they now use main's property
  directly. That import was also the only reason
  `test_vpi_release_coincident_with_an_edge_matches_the_vector_testbench` failed: VZTRIG's
  test.yaml declares `work_unit: toy`, so main's property serves it unchanged.
- `tools/tests/test_lint.py`: `test_portability_missing_table_lint_cli_exits_0` builds its
  tree with `_bins_tree` (FDRE's real catalog entry, every bin accounted), so main's
  `bins-accounted` rule runs for real and passes. The rule itself is unchanged.
- The hand-merged spots were reviewed: `cli.py` (crosscheck, portability, verilatorize,
  `status generate`), `status.py` (`record`, `render_portability`), `lint.py` (docstring,
  `check_portability` wired into `lint`) and `test_lint.py`. There are no duplicate
  definitions, imports or commands. `status generate` still writes PORTABILITY.md when
  `build/portability/*.json` holds a full run, which
  `test_status_generate_also_writes_portability_when_results_exist` covers.

## Test results
- `test_runner_verilator.py`: 61 passed. The portability and bins lint tests: 30 passed.
- `xut lint --branch`: 0 errors, 1 warning (PORTABILITY.md is not generated off main).
- The full-suite result is in the session report.

## Next steps
- The orchestrator pushes the rebased branch.
