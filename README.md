# xilinx-unittests

A comprehensive, cross-checked test suite for the design primitives documented
in the Xilinx/AMD libraries guides, starting with 7-series
([UG953](https://docs.amd.com/r/en-US/ug953-vivado-7series-libraries)).

Each test runs:

- in the **Xilinx simulator** (Vivado xsim),
- in **open-source simulators** ([Icarus Verilog](https://github.com/steveicarus/iverilog)
  and [Verilator](https://github.com/verilator/verilator)),
- on **real Artix-7 hardware** at [fpgas.online](https://ps1.fpgas.online/fpgas/),

and the results from all of these are **cross-checked** against each other and
against independent golden models written from the documentation. Because
every test can also be built by different toolchains (Vivado, yosys +
nextpnr-xilinx, F4PGA/VPR), the suite doubles as a toolchain validation
suite.

## Status

Early bootstrap. See [`status/PROGRESS.md`](status/PROGRESS.md) for the
per-primitive test matrix, [`status/TODO.md`](status/TODO.md) for outstanding
work, and [`log/`](log/) for the running progress log.

## Documentation

- Design: [`docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md`](docs/superpowers/specs/2026-09-25-xilinx-primitive-test-suite-design.md)
- Contributor and agent rules: [`AGENTS.md`](AGENTS.md)

The Xilinx/AMD PDF guides are not redistributed here. Run
`tools/fetch_docs.py` to download them into `.cache/`.

## License

Apache License 2.0; see [`LICENSE`](LICENSE).
