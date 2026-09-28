# LUT2: doc-gap in 7series.LUT2.L0.illegal_init

- Class: doc-gap
- Test: 7series.LUT2.L0.illegal_init (configuration `init_x`, INIT=4'bxxxx, all x)
- Flow / model source: rtl / unisim-2025.2
- Also seen: rtl / unisim-gh-2020.1
- Runners: xsim, iverilog (unisim-2025.2); iverilog (unisim-gh-2020.1)
- First seen: luts Task B6 full run, 2026-09-28, at 59252e3
- Status: open

## Evidence

UG953 v2026.1 p492 (the LUT2 Available Attributes table) gives INIT's allowed values as
a 4-bit HEX value. An INIT with x digits is not one of them. The test declares
`expect=reject`: a simulation with that INIT should stop before its first sample.

UNISIM accepts it on every runner that ran the test: unisim-2025.2 on xsim and iverilog,
and unisim-gh-2020.1 on iverilog. Each run reached `XUT_DONE` ("expected rejection, got
acceptance"), so it is a `fail`. Verilator is declared unsupported for this test.

## Analysis

UG953 lists the legal INIT values, but it does not say that a simulation model rejects an
illegal one at run time, or what it does with one. The expectation of a runtime rejection
is therefore the test's, not the documentation's, and this is a gap in the documentation
rather than a model or simulator bug.

By the user's decision of 2026-09-28, the reject test is kept, not removed as the
playbook's Task A6/D8 rule would have it. The flops unit removed its INIT=1'bx reject
tests under that rule earlier. Instead, the test lists this finding in its
`expected_divergence`, and the expected outcome (reject) stays as it is. The finding
stays open until UG953 states a rejection (or states that none is required), or the
simulators reject the value.

Note on the tooling: `xut crosscheck` classifies trace disagreements. A reject test's
acceptance is a result `fail` with no trace disagreement, so crosscheck still reports it
as an unexplained fail (exit 4) and the `expected_divergence` entry as matching no
disagreement. Mapping a reject-test acceptance to its listed finding needs infra.
