# Xilinx Primitive Test Suite — Design

- Status: revision 3.1 (2026-09-25). Rev 2 incorporated the technical and
  requirements/process reviews of rev 1. Rev 3 adds the findings of the step-2
  toolchain research: Verilator cannot compile stock UNISIM, openXC7 has moved
  to `openXC7/nextpnr`, and F4PGA/VPR and fasm2bels are stale.
  Rev 3.1 pins Verilator to v5.048, built from the upstream git tag, because
  cocotb 2.0.1 needs Verilator 5.036 or later. The apt 5.032 is too old.
  cocotb-on-Verilator is required.
  Rev 3.1 also guards the `deassign` rewrite of §6.2 step 2 with
  `X__ovr_sel != 0`, wrapped in `begin ... end` so that no `else` can dangle.
  It also states in §8 that an `expected_divergence` never masks a
  disagreement: it is reported as `known-divergence`.
- Owner: Tim 'mithro' Ansell
- Repository: https://github.com/mithro/xilinx-unittests (Apache-2.0)

## 1. Purpose

Build a comprehensive, well-documented test suite for every design primitive in
the Xilinx/AMD libraries guides. It must:

1. Exercise **all functionality documented by Xilinx** for each primitive:
   every port, every attribute (legal values sampled per §4.2), and every
   documented *behavioural claim* (priorities, modes, latencies, interactions).
2. Run on:
   - the Xilinx simulator (Vivado **xsim**),
   - fully open-source simulators (**Icarus Verilog**, **Verilator**),
   - **real hardware** via the boards on **fpgas.online**.

   Tests run on every runner **unless declared unsupported with a reason**.
   Nothing is skipped silently.
3. Provide **small unit tests** as well as **larger functional/integration tests**.
4. **Cross-check** results between every way a test can be run. The references
   are the documentation, the vendor simulation models and silicon.
5. Be usable to **validate FPGA toolchains** (Vivado; yosys + openXC7
   nextpnr; F4PGA/VPR as a legacy flow).
6. Carry **detailed documentation per test**: what it exercises, why it is
   useful, what it misses, and what it is related to.

### Success criteria

- Every catalogued primitive has a status entry. The generated matrix shows, per
  primitive, the level × runner × flow results, plus port, attribute and
  behavioural-claim coverage.
- Any divergence between oracles is a classified finding. It is never silently
  ignored, and never "fixed" by weakening a test.
- A toolchain developer can build the suite with their flow and get a
  pass/fail matrix against the reference.

## 2. Scope and phasing

- **First target: 7-series**, as documented in UG953 (2026.1; 2025.2 is also
  recorded): 103 primitives, 12 UniMacros and 20 XPMs. All Xilinx hardware on
  fpgas.online is Artix-7, and prjxray, openXC7 nextpnr and VPR support only
  7-series.
- The framework is family-agnostic. **UltraScale** (UG974, 131 primitives)
  follows later, as a simulation-only family.
- Primitives that UNISIM provides but UG953 does not document (PS7, GT*E2,
  PHASER_*, PCIE_2_1, MUXCY, XORCY, ...) are catalogued as `undocumented` and
  are out of scope until the documented set is done.
- **Out of scope: timing.** That covers SDF, `XIL_TIMING`, setup/hold checks
  and path delays. IDELAYE2/ODELAYE2 are checked through tap state
  (CNTVALUEOUT) and relative ordering, not absolute delay values.
- **Initial hardware:** Digilent Arty A7-35T only. **Initial Vivado:** 2025.2
  only. NeTV2, Acorn and LiteFury boards, other Vivado versions, and publishing
  container images to ghcr are all deferred until after fan-out (§16 step 5).

## 3. Sources of truth

| Source | Role | Location |
|---|---|---|
| UG953 2026.1 (and 2025.2) PDF | Specification | Downloaded by `tools/fetch_docs.py` into `.cache/docs/`. A local copy may be supplied instead. **Never committed** (AMD copyright). |
| UG953 HDL templates zip | Instantiation templates | `.cache/docs/` |
| `catalog/7series/<PRIM>.yaml` | Generated facts: ports, directions, widths, port class (§5.1), attributes with types, allowed values and defaults, group, page references, behavioural claims | committed; written only by the extractor (infra) |
| `catalog/7series/<PRIM>.overrides.yaml` | Hand corrections and additions, merged over the generated file at load time | committed; owned by the primitive's work unit |
| XilinxUnisimLibrary (Apache-2.0, Vivado 2020.1) | Open reference models, used in CI | git submodule `third_party/XilinxUnisimLibrary` |
| Vivado 2025.2 UNISIM, `retarget/`, `secureip/` | Vendor reference models | host `/opt/xilinx/Vivado/2025.2`; never copied into the repo |
| `models/xut_models/` | **Independent Python golden models, written clean-room from UG953** | committed |
| Silicon (Artix-7 on fpgas.online) | Ground truth | remote |

The catalog contains facts and page references only. It never quotes AMD prose
at length; a behavioural claim is a paraphrase plus its page number.

**Extraction method.** The extractor parses the UG953 port and attribute
tables. It cross-checks port names and widths against the UNISIM `.v` module
header and the HDL template for the same primitive, and flags every mismatch
in `catalog/EXTRACTION_REPORT.md` for a human to resolve through an overrides
file.

**Behavioural claims.** A claim is a single documented statement about
behaviour, for example "R has priority over CE" or "DO is valid one cycle
after the rising CLK edge when DOA_REG=0". Each claim gets a stable ID
(`FDRE.C3`) and a page reference. Tests declare which claim IDs they exercise.

**Golden-model independence (clean room).** Model authors write from UG953
alone and do not read UNISIM source. Each modelled behaviour carries a
provenance tag: `doc:<page>` if UG953 states it, `inferred:<reason>` if it
had to be inferred. Where the documentation gives only a range or a property
(for example FIFO flag latency), the model states a *property check* rather
than an exact value. `doc-vs-model` findings against `inferred` behaviour are
downgraded to `doc-gap`.

## 4. Test taxonomy

### 4.1 Levels

| Level | Name | Content |
|---|---|---|
| L0 | Smoke | Instantiates and elaborates with default and sampled attribute values. Illegal attribute values are rejected. The UNISIM models reject them at **runtime** (`$finish`), so L0 runs a short simulation. |
| L1 | Unit | One test per behavioural claim, port behaviour, attribute or mode. |
| L2 | Functional | Exhaustive where tractable, otherwise constrained-random coverage of inputs × attributes against the golden model. |
| L3 | Integration | Multi-primitive designs, e.g. a DSP48E1 FIR with cascades, a BRAM cascade, a FIFO under CDC, an ISERDES/OSERDES loopback, MMCM → BUFG → logic. |

### 4.2 Attribute sampling

- An enumerated attribute is covered **for every value**.
- An integer or bit-vector attribute (INIT, INIT_xx, delay taps, DIVIDE)
  is covered by boundary values, walking-ones/zeros, and seeded random samples.
  The sampling plan for each attribute is recorded in `test.yaml`.
- Declared attribute **crosses** are covered pairwise. Examples are READ_WIDTH ×
  WRITE_WIDTH, and the DSP48E1 AREG/BREG × ACASCREG × INMODE combinations.

### 4.3 Test styles

All three styles are used together.

1. **Vector tests** (`vectors/`) form the canonical cross-check format (§5).
   A generator uses the golden model to produce the stimulus and the expected
   trace. One generic testbench replays the stimulus in every simulator and
   netlist simulation. The hardware harness replays the same stimulus when it
   can be rendered on hardware (§7).
2. **Hand-written SystemVerilog testbenches** (`sv/`) cover what vectors cannot
   express: clock management, X-propagation, GSR/GTS/GRESTORE, runtime
   attribute rejection, DRP transactions.
   - They use the common SV subset of xsim, Icarus `-g2012` and Verilator
     `--timing`; any deviation from that subset is declared in `test.yaml`.
   - They also **emit an `.xtr` trace** of their checkpoints, so they take
     part in cross-checking across simulators.
3. **cocotb tests** (`cocotb/`) run long constrained-random, model-based
   sessions on Icarus and Verilator (cocotb has no xsim backend).
   - Every failing seed is frozen into a new vector test, which then runs on
     xsim and hardware.
   - cocotb tests also emit an `.xtr` trace, so Icarus and Verilator can be
     compared with each other.

## 5. Canonical DUT wrapper, stimulus and trace formats

### 5.1 Port classes

The catalog assigns every primitive port a class. The class tells the
generator how the port may be driven and tells the harness how to realise it.

| Class | Examples | Rules |
|---|---|---|
| `clock` | FDRE.C, RAMB36E1.CLKARDCLK, BUFGCTRL.I0 | Driven only by declared clocks or by explicit edge events |
| `async` | FDCE.CLR, FDPE.PRE, FIFO36E1.RST, BUFGCTRL.S0/CE0 | Must never change in the same event as a clock edge or another async/gate bit. Recovery and removal relative to a clock are their own events with a declared minimum separation. |
| `gate` | LDCE.G, LDPE.G | Same rules as `async` |
| `data` | FDRE.D, CE, R | Change only between clock edges |
| `inout` | IOBUF.IO | Split into `<p>__drive_en` and `<p>__drive_val` (inputs) plus `<p>__obs` (a resolved 4-state observation) |
| `clock_out` | MMCME2_ADV.CLKOUT0, BUFR.O | Observed through clock observers (§5.4), never sampled directly |
| `pad` | IBUF.I, OBUF.O | Only realisable on hardware through the pad harness (§7.3) |
| `drp` | MMCM/PLL/XADC DADDR/DI/DO/DEN/DWE/DRDY | Checked at transaction level (§5.5) |

### 5.2 DUT wrapper

`xut wrap` generates one wrapper per *test configuration* (a primitive plus an
attribute set):

```verilog
module xut_dut #(...) (
  input  wire [NCLK-1:0] clk,
  input  wire [NIN-1:0]  in_vec,
  output wire [NOUT-1:0] out_vec
);
```

- A sidecar `xut_dut.map.json` records the port → bit mapping, the class of
  each bit, and the attributes.
- The primitive instance carries `(* DONT_TOUCH = "TRUE", KEEP_HIERARCHY = "TRUE" *)`
  and yosys `keep`, so no flow can optimise it away.
- **Global signals** (GSR, GTS, GRESTORE, and the JTAG_* signals BSCANE2
  uses) are not ports. They are driven through a dedicated `glbl` channel in
  the stimulus. Simulation implements it by forcing `glbl`. Hardware can only
  drive GSR (through STARTUPE2.GSR, see §7.2); for any other glbl event the test
  is sim-only.

### 5.3 Stimulus (`.xvec`) and trace (`.xtr`)

The stimulus is an **ordered, timed event list**. Times are in picoseconds.

```
# xut-vec 2  prim=FDCE cfg=init1 nin=4 nout=1 nclk=1 settle_ps=120000 seed=17
clock  clk0  period=10000 phase=0 duty=50 mode=stepped   # or mode=free
t=120000  set   in[3:0]=0x1          # data
t=121000  edge  clk0 r
t=125000  set   in[2]=1              # async: alone in its event
t=126000  sample S1
```

- `settle_ps` is the wait before the first event. It is at least
  max(ROC_WIDTH, GRES_START+GRES_WIDTH) from `glbl`, plus margin.
- A `mode=free` clock runs continuously. Primitives that measure their input
  clock, such as the MMCM and PLL, need one.
- Events at the same time are allowed in simulation only if the file marks
  them `simultaneous`. The generator validates the class rules from §5.1 and
  marks the file `hw_renderable: yes|no`, with a reason when it is not.
- `sample <label>` records out_vec.

The trace has one line per sample:

```
# xut-trace 2  runner=iverilog flow=rtl model=unisim-2025.2 seed=17
S1  0b1
```

- Values are written **per bit** (`0 1 x z`) and grouped by port in a
  readable form.
- The expected trace carries a per-bit *don't-care* mask. A bit may be masked
  only where the golden model declares it undefined by the documentation.

### 5.4 Clock observers

These are simulated/synthesised helper modules that are part of the wrapper.
Clock outputs connect to them:

- an edge counter over a window, which gives frequency;
- a phase/ordering sampler against a reference clock;
- a glitch detector that flags pulses shorter than a threshold.

Their counters appear as ordinary `out_vec` bits. The same observers are used
in simulation and on hardware.

### 5.5 DRP transactions

Tests that use DRP declare the transaction list: address, write data, and
expected read data. The check passes when each read returns its expected
value, with DRDY arriving within a latency bound. Exact DRDY cycle timing is
not checked.

### 5.6 Comparison and runner capabilities

Each runner declares what it can observe:

| Runner | x/z observable | Notes |
|---|---|---|
| xsim, iverilog | yes | 4-state |
| verilator | no | Each test runs **twice**, with `--x-assign unique --x-initial unique` and two recorded seeds. Any difference between the two runs is reported as `x-dependence`. |
| hw | no | Only 0/1 is observable. The run repeats N times; any difference is reported as `nondeterminism`. |

If a runner observes `x` where the expectation is a defined value, the test
fails.

## 6. Flows and runners

A *flow* turns HDL into something executable. A *runner* executes it.

| Flow | Detection points (each is simulated with the same vectors) |
|---|---|
| `rtl` | wrapper + UNISIM |
| `vivado` | post-synth funcsim netlist; post-route funcsim netlist; bitstream-derived netlist (§6.1); bitstream on hw |
| `yosys` | `synth_xilinx` netlist, simulated against UNISIM |
| `openxc7` (yosys + `openXC7/nextpnr` himbaechel-xilinx + prjxray) | yosys netlist; post-route netlist (§6.1); bitstream on hw |
| `vpr` (F4PGA, legacy) | yosys netlist; post-route netlist (§6.1); bitstream on hw |

- A bitstream-derived netlist (§6.1) gives all P&R tools one like-for-like
  comparison point.
- After every flow the cell type and attributes of the DUT are extracted and
  compared with the configuration, which catches silent retargeting.
- `INIT_FILE` and other file-based attributes are tested explicitly per flow.
  The simulation working directory is pinned.

| Runner | Environment |
|---|---|
| `python` | golden model only; produces expected traces |
| `xsim` | Vivado 2025.2, sourced in a subshell |
| `iverilog` | container |
| `verilator` | container, `--timing`; `glbl` compiled as a second top; UNISIM models pass through `xut verilatorize` first (§6.2) |
| `hw` | fpgas.online |

### 6.1 Post-route netlists and fasm2bels

`fasm2bels` (FASM → UNISIM Verilog) is the planned like-for-like post-route
netlist source for every flow, but its last real commit was 2023-03. Step 4
therefore starts with a spike, and **only** these outcomes are acceptable:

1. fasm2bels works for xc7a35t with current prjxray, possibly with local
   patches kept in `third_party/` patches; or
2. each tool's own post-route export is used instead: nextpnr's
   `--write` JSON converted to Verilog with yosys, VPR's post-route netlist,
   Vivado funcsim.

Either way, hardware remains the final arbiter.

### 6.2 Verilator and UNISIM (`xut verilatorize`)

Verilator 5 rejects the Verilog-1995 procedural `assign`/`deassign`. This is a
hard `UNSUPPORTED` error. The construct appears in 40 of 249 UNISIM models.

**Triggers.** A forced reg's *triggers* are the signals in the sensitivity
lists of the `always` blocks that contain its `assign`/`deassign`. They are
**derived from the AST by the tool, never hand-labelled**. A trigger is either
`glbl.GSR` or a primitive input port. Each sensitivity-list signal is traced
through its **full transitive fan-in cone**, crossing continuous assigns,
combinational logic **and** registered stages, to every root it depends on.

For example, MMCME2_ADV's `rst_int` is a register fed by
`rst_input = RST | PWRDWN`, so its triggers are **both** `RST` and `PWRDWN`.
Clocks met while crossing registered stages are recorded as *enablers*, which
must be running while the stimulus pulses the triggers; they are not triggers
themselves. Many constructs have several triggers, for example
`@(gsr_in or clr_in)` in BUFR and `@(gsr_in or r_in or s_in)` in IDDR/ODDR.
The derived trigger list for each model is recorded in
`status/PORTABILITY.md`.

`xut verilatorize` rewrites the construct with a **generic shadow-register
transform**. It works on the pyslang AST, never on regex text, so it cannot
false-match identifiers that merely contain `assign` or `deassign`. For each
procedurally-forced reg `X`:

1. Every ordinary procedural write to `X` is redirected to a new reg
   `X__base`. This covers every `always`/`initial` block and task body, whole
   and bit/part-select lvalues, and self-referencing writes (for example the
   SRL shift chain, which reads `data` while writing it).
   - Reads of `X` are left alone, so they see the overridden value exactly as
     before.
   - Blocking vs non-blocking form and intra-assignment delays are preserved
     exactly, so scheduling order is unchanged.
2. Each `assign X = e_k;` is replaced by `X__ovr_sel = k;`, and each
   `deassign X;` by
   `begin if (X__ovr_sel != 0) begin X__base = X; X__ovr_sel = 0; end end`.
   The second form preserves the Verilog rule that a reg keeps its forced value
   after `deassign`. The guard keeps a `deassign` of a reg that is not forced a
   no-op, as Verilog requires. Without it, a not-yet-propagated `X` could
   overwrite an `X__base` written earlier in the same time step. The outer
   `begin ... end` makes the replacement a single statement, so an `else` that
   followed the original `deassign` still binds to its own `if`.
3. `X` becomes a net:
   `assign X = (X__ovr_sel == 0) ? X__base : (X__ovr_sel == 1) ? e_1 : ...`.
   Because the `e_k` are evaluated continuously, this preserves the
   continuous-override semantics even when `X` has several writers (for
   example, MMCME2_ADV `clkout_en1`).
4. Any construct the transform cannot prove it handles makes it fail loudly,
   naming the model. The model is then `verilator: unsupported` in
   `status/PORTABILITY.md`. Nothing degrades silently.

Transformed copies go to `build/verilatorized/<model-source>/` and are
**never committed**. The transform has fixture unit tests for each case:

- single writer;
- multiple writers;
- `deassign` value retention;
- non-constant override expressions;
- multiple triggers;
- bit/part-select writes;
- task-body writes;
- self-referencing writes;
- non-blocking writes with delays;
- interaction with asynchronous CLR/PRE.

**Equivalence validation** is a cross-check in its own right:

- The portability table lists every transformed model with its derived
  triggers.
- For each one, a **generated, mandatory equivalence stimulus** runs on Icarus
  against both the original and the transformed model.
- Every trigger (GSR through the glbl channel; ports directly) is pulsed
  **mid-simulation**, several times. Each is pulsed **independently**, and
  every pair of triggers is pulsed **in overlapping combination**.
- The pulses are timed both with and without coincident clock edges and
  asynchronous-control activity.
- Additionally, every ordinary test on the `verilator` runner also runs on
  Icarus against the transformed model.
- Any trace difference is a `transform-bug`, and it blocks the Verilator
  results for that model.
- Icarus is 4-state, so this check also covers X-propagation differences that
  2-state Verilator could never reveal.
- `xut lint` fails if a transformed model has no equivalence stimulus.

Community rewrites (`uwsampl/verilator-unisims`,
`oliverbunting/verilator-unisims`) are used as references, not as
dependencies.

**Model identity.** A runner result names its model source:
`unisim-2025.2` on the host, or `unisim-gh-2020.1` from the submodule in CI.
Cross-checks compare like-for-like model sources. Comparisons across model
versions are a separate, explicit report.

**Portability table.** A smoke run of every UNISIM model in each simulator
container generates `status/PORTABILITY.md`. It lists which models compile and
elaborate, with the reasons for any that don't: STARTUPE2's strength-resolved
GSR driver under Verilator, UDPs, `tri0/tri1`, `real`, secureip. Test
declarations of `unsupported` must match this table.

The simulation defines `XIL_TIMING`, `XIL_XECLIB`, `XIL_DR` and
`XIL_ATTR_TEST` are pinned per run (default: all undefined) and recorded.

`result.json` records:

- tool versions and the container digest;
- model source, seeds, and the stimulus and bitstream hashes;
- for `hw`: board DNA, serial number and site;
- duration, and one of `pass | fail | error | skip` with a reason.

## 7. Hardware harness (fpgas.online)

### 7.1 Stepped fabric harness (default)

- **Stimulus.** Timed events are compiled into a BRAM image of harness
  operations: set in_vec bits, pulse a clock, sample.
- **Sequencer.** It runs on a conservative system clock.
  - The DUT clock is a harness flip-flop routed through a BUFG.
  - Correctness holds by construction: there are at least N system cycles
    between an in_vec change, the next DUT edge, and the next capture.
    N is chosen to cover worst-case skew.
  - Vivado gets generated-clock and max-delay constraints; the open flows rely
    on the margin alone.
- **Async events.** Async and gate events are separated from edges as §5.1
  requires.
- **Multi-DUT packing.** One bitstream holds many configurations, selected by a
  harness register. This keeps the number of builds manageable.
- **Self-test.** Every bitstream contains a known-good passthrough and a
  counter channel. The harness runs them first, so a toolchain-under-test bug
  in the harness itself is reported as `harness-error`, not as a DUT failure.
- **UART dumper.** It streams `.xtr` with a header carrying the build ID,
  the configuration and a CRC.

### 7.2 GSR-immune harness state

Tests that pulse GSR through STARTUPE2 also reset the harness's flip-flops. The
harness therefore keeps its sequencer state in BRAM/LUTRAM, which GSR does not
affect, and re-enters from there. Until that exists, GSR/INIT tests are
`hw: unsupported`.

### 7.3 Pad harness

IBUF*, OBUF*, IOBUF*, IDDR/ODDR/IDDR_2CLK, ISERDESE2/OSERDESE2,
IDELAYE2/ODELAYE2 (with IDELAYCTRL and a 200 MHz REFCLK), BUFIO and BUFR
must sit on IOB/ILOGIC/OLOGIC sites; BUFIO and BUFR also need clock-capable
pins or a BUFMR.

- **Wiring.** `hw/boards/arty_a7_35t/pads.yaml` lists the usable pins,
  clock-capable pins and bank VCCO. Loopbacks use the Arty PMOD to Pi PMOD HAT
  wiring: 5 usable lanes, with the Pi driving and reading them as a second
  stimulus/observation channel.
- **Voltage limits.** Arty I/O banks are 3.3 V, so LVDS/differential
  *outputs* are `hw: unsupported` on this board, with that reason.

### 7.4 Configuration primitives

Each configuration primitive declares its oracle:

| Primitive | Oracle / handling |
|---|---|
| STARTUPE2 | One per device and shared with the harness. The GSR/GTS drive is tested via §7.2. USRCCLKO/CCLK is sim-only for now. |
| ICAPE2 | Reads IDCODE (a known constant per part) and readback registers. **IPROG is forbidden** because it reboots the device. The sim model uses `SIM_CFG_FILE_NAME`. |
| BSCANE2, CAPTUREE2 | The host drives JTAG through openFPGALoader/OpenOCD on the Pi while the design runs. |
| DNA_PORT, EFUSE_USR | The host reads the per-die value over JTAG. The runner passes it in as `SIM_DNA_VALUE`/`SIM_EFUSE_VALUE`, so sim and hw agree. |
| USR_ACCESSE2 | The value comes from a bitstream option. Where an open flow cannot set it, that flow marks the test `unsupported`. CFGCLK is checked by frequency range only. |
| FRAME_ECCE2 | Needs readback-CRC bitstream options and a frame file in sim. The initial tests only check the no-error state. |
| XADC | Analog readings are compared within tolerances (temperature, VCCINT, VCCAUX), not bit-exact. |

### 7.5 Board access

- Access is SSH to the board's Raspberry Pi. Bitstreams go over via `scp`,
  are loaded with `openFPGALoader -b arty`, and results come back over the UART
  (`/dev/ttyUSB1`, 115200).
- **Board lock.** A lock file on the Pi records the owner, the time and a TTL.
  Locks past their TTL are broken.
- **Transport errors** (SSH, UART CRC) are retried once. A board that fails
  the self-test is marked bad for the session.
- **Adapter.** A minimal `BoardSession` adapter allows a later switch to the
  planned fpgas.online lease API.
- **Preflight** (§15) checks SSH connectivity and keys.

## 8. Cross-checking and findings

`xut crosscheck <test-id>` gathers every trace for a test, compared
like-for-like by model source, and produces a matrix. Disagreements are
classified:

| Class | Meaning |
|---|---|
| `doc-vs-model` | Golden model ≠ all UNISIM simulators on a `doc:`-provenance behaviour |
| `doc-gap` | Same, but on `inferred` behaviour, i.e. the documentation is silent |
| `sim-divergence` | UNISIM simulators disagree |
| `x-dependence` | The two Verilator X-seed runs disagree |
| `transform-bug` | Icarus on transformed UNISIM ≠ Icarus on original UNISIM |
| `flow-mismatch` | A flow's post-synth or post-route netlist ≠ RTL: a toolchain bug |
| `silicon-mismatch` | Hardware ≠ reference |
| `nondeterminism` | Repeated hardware runs disagree |
| `harness-error` | The harness self-test failed |
| `known-divergence` | Any of the above, listed in the test's `expected_divergence` (reports the original class and the finding id) |

- **Recording.** Each finding goes in `findings/<PRIM>-<slug>.md`, is linked
  from the primitive's README, and may be referenced by an
  `expected_divergence` entry in `test.yaml`.
- **An expected divergence never masks.** Expected bits stay defined, and the
  disagreement is still computed and reported, classified `known-divergence`
  with the finding id. It shows in PROGRESS.md and TODO.md while the finding
  is open. `xut crosscheck` fails only on disagreements that no
  `expected_divergence` lists.
- **Weakening tests is forbidden.** A test is never made weaker to hide a
  finding.

## 9. Coverage

- **Functional bins** are generated from the catalog: ports × classes,
  attribute values (§4.2), declared crosses, and behavioural claims. A test's
  `exercises:` list marks bins as covered, and simulation of the golden model
  confirms that the stimulus actually reaches them.
- **Model code coverage.** UNISIM line/branch coverage (Verilator `--coverage`)
  shows which model branches no test reaches. It is reported in status and
  first added in step 5.

## 10. Repository layout and ownership

```
LICENSE  README.md  AGENTS.md  pyproject.toml         (infra-owned)
docs/work-units.yaml                                  (infra-owned; §13)
docs/review/                                          reviewer prompts (infra-owned)
catalog/7series/<PRIM>.yaml                           generated (infra)
catalog/7series/<PRIM>.overrides.yaml                 work unit
models/xut_models/7series/_common/<family>.py         work unit (shared family model)
models/xut_models/7series/<prim>.py                   work unit
tests/7series/<group>/<PRIM>/{test.yaml,README.md,vectors/,sv/,cocotb/}
tests/7series/integration/<name>/                     integ/* branches
tools/xut/  hw/  containers/  .github/                infra
third_party/XilinxUnisimLibrary                       submodule (infra; any bump = full re-run)
status/7series/<PRIM>.yaml                            work unit
status/PROGRESS.md  TODO.md  LOG.md  PORTABILITY.md   GENERATED on main only
log/<YYYY-MM-DDTHHMM>-<branch-slug>-<slug>.md         anyone (unique names)
findings/<PRIM>-<slug>.md                             work unit
```

`<group>` is the UG953 PRIMITIVE_GROUP, lower case: `advanced`, `arithmetic`,
`blockram`, `clb`, `clock`, `configuration`, `io`, `register`, plus
`unimacro`, `xpm` and `integration`.

Every source file carries `SPDX-License-Identifier: Apache-2.0`, and `xut lint`
checks for it.

## 11. Metadata and status

`test.yaml` (per primitive):

```yaml
primitive: FDRE
family: 7series
work_unit: flops
doc_refs: [{guide: UG953, version: "2026.1", section: FDRE, page: 562}]
tests:
  - id: 7series.FDRE.L1.reset_over_ce
    level: L1
    style: vector                  # vector | sv | cocotb
    exercises: [port:R, port:CE, claim:FDRE.C3]
    attr_sampling: {INIT: [0, 1]}
    runners: {python: yes, xsim: yes, iverilog: yes, verilator: yes, hw: yes}
    flows: [rtl, vivado, yosys, openxc7, vpr]
    related: [7series.FDSE.L1.set_over_ce]   # a missing target is a lint warning
    gaps: ["setup/hold timing out of scope"]
```

`status/7series/<PRIM>.yaml` records:

- results per level × runner × flow;
- the **tree hash** of the test directory and the tool/model versions it was
  measured with (tree hashes survive rebases, commit SHAs do not);
- open findings;
- covered and uncovered bins.

**Generated files.** `xut status` builds PROGRESS.md (the matrix), TODO.md
(every uncovered bin, unsupported cell and open finding) and LOG.md (the
chronological index of `log/`).

- **Branches never commit generated files.** After each merge the orchestrator
  regenerates them on `main` in a dedicated `status: regenerate` commit.

## 12. Per-test documentation

Each primitive's `README.md` follows `docs/templates/primitive-README.md`:

- overview and UG953 reference;
- a table of tests (ID, level, style, bins and claims exercised);
- **why each test is useful**;
- the oracle used;
- **known gaps and what is not tested**, and why;
- runner support and expected divergences, with links to findings;
- **related tests**;
- how to run it.

`xut lint` enforces that:

- every test is documented;
- every bin is covered or listed as a gap;
- the portability table agrees with the tests' `unsupported` declarations;
- SPDX headers are present;
- the branch touched only paths its work unit owns (§13).

## 13. Parallel development workflow

### 13.1 Work units and ownership

`docs/work-units.yaml` maps each **work unit** to its primitives and the paths
it owns. Examples:

- `flops`: FDRE, FDSE, FDCE, FDPE
- `latches`: LDCE, LDPE
- `luts`: LUT1–LUT6, LUT6_2, CFGLUT5
- `lutram`: RAM*, ROM*
- `srl`: SRL16E, SRLC32E
- `bram`: RAMB18E1, RAMB36E1
- `bram_fifo`: FIFO18E1, FIFO36E1
- `dsp`: DSP48E1
- `mmcm_pll`: MMCME2_*, PLLE2_*

A unit owns its primitives' test directories, overrides, models (including
`_common/<family>.py`), status files and findings.

### 13.2 Branch types

| Branch | Scope |
|---|---|
| `unit/7series/<unit>` | one work unit |
| `infra/<topic>` | shared code |
| `integ/<name>` | one L3 design (its own directory) |
| `docs/<topic>` | specs and plans |

### 13.3 Branch mechanics

- **Worktrees.** Each branch works in its own worktree under
  `../xilinx-unittests-worktrees/<branch-with-dashes>`.
- **Path lint.** `xut lint --branch` fails if a branch touches paths it does
  not own.
- **Infra dependencies.** A unit branch that needs an infra change records a
  TODO and continues, *or* stacks on the open `infra/*` branch. Merge order is
  always infra first. The orchestrator then rebases the dependent branch and
  re-runs its tests before reviewing it.
- **Small commits.** Commit after every meaningful change, including log and
  status updates. The subject is prefixed with the unit or area
  (`flops: add FDRE L1 reset-over-CE vector test`). A commit-msg hook enforces
  the prefix.

### 13.4 Review and merge gate

- **Every branch becomes a GitHub PR**, including infra, integ and docs.
- **Two fresh reviewer agents** review it, using fixed prompts from
  `docs/review/`:
  - (a) code quality, style and common HDL/Python/verification mistakes;
  - (b) technical correctness against UG953 (and against the clean-room rule
    for models), coverage and documentation completeness.
- Reviewers post findings as PR review comments via `gh`. Each finding is
  marked **must-fix** or **nit**. The implementer addresses them in follow-up
  commits, and the reviewers re-review.
- **Merge gate:**
  - `xut lint` passes;
  - the open-source CI is green;
  - both reviewers approve with no open must-fix;
  - the orchestrator rebase-merges (keeping the small commits) and then
    regenerates status on `main`.

### 13.5 Concurrency

At most **two sub-agents in total, reviewers included**, at any time. The
normal schedule is one implementer plus one reviewer. The orchestrator itself
does not count.

### 13.6 Status cadence

Every 30 minutes, driven by a timer rather than by task completion, the
orchestrator reports progress to the owner and writes a `log/` entry.

## 14. Error handling principles

- **No silent skips.** Every result is `pass | fail | error | skip`; `skip`
  always carries a reason.
- **Errors are distinct from failures.** Tool crashes, licence problems and
  timeouts are `error`, not `fail`.
- **Retries.** Transport errors are retried once. An error is never retried
  into a pass.
- **Full logs.** Command output always goes to log files. Nothing is filtered
  inline.

## 15. Preflight (`xut doctor`)

`xut doctor` checks:

- the Vivado 2025.2 path;
- docker, and that the containers build;
- `gh` auth;
- the submodule is present;
- the PDF can be downloaded, or a local copy exists;
- fpgas.online SSH reachability and keys.

It reports what is missing, and which runners are available as a result.

## 16. Build order

1. **Bootstrap.**
   - AGENTS.md, work-units.yaml, review prompts, templates.
   - `fetch_docs`, and catalog extraction for all 103 primitives with an
     extraction report.
   - The status schema, `xut status`, `xut lint`, and `xut doctor`.
2. **Core infra and pilot.**
   - One simulator container, `FROM debian:trixie-slim@<digest>` with apt
     `iverilog=12.0-2+b1`, Verilator v5.048 built from the upstream git tag
     (`https://github.com/verilator/verilator`, tag `v5.048`, commit
     `d0aa828c217410fffc73d92077b6f4f54830357c`) in a multi-stage build on the
     same base, and pip `cocotb==2.0.1`.
   - `xut verilatorize`, with its Icarus equivalence check.
   - The wrapper generator, `.xvec` and `.xtr` formats, and the vector
     testbench.
   - The python, xsim, iverilog and verilator runners, crosscheck, and the
     portability table.
   - Pilot: the `flops` unit (FDRE first) end-to-end in all three styles.
3. **Hardware.**
   - The stepped fabric harness on Arty A7-35T, the Vivado flow, and the `hw`
     runner.
   - Pilot on `flops` and `luts`.
4. **Toolchain flows.**
   - Vivado netlists, yosys, and openXC7 (`openXC7/nextpnr` + prjxray,
     via Nix or a locally built image).
   - The fasm2bels spike (§6.1).
   - F4PGA/VPR (legacy; lowest priority).
   - Confirm that prjxray/nextpnr support the -1L grade (xc7a35ticsg324-1L).
5. **Fan-out**, group by group: register → clb → blockram → arithmetic →
   clock → io (with the pad harness) → configuration → advanced.
   - Then UniMacros, XPMs, L3 integration and model code coverage.
6. **Deferred items.** Extra boards, extra Vivado versions, publishing to ghcr,
   and UltraScale (UG974, simulation-only).
