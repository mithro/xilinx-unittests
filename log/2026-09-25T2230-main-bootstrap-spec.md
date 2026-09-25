# 2026-09-25 22:30 — Bootstrap: research, spec rev 1 → rev 2

- Researched fpgas.online (Artix-7 only: Arty A7-35T primary; SSH to per-board Pi, openFPGALoader, UART readback; no lease API yet).
- Downloaded UG953/UG974 (2025.2 + 2026.1) via the docs.amd.com khub API; 103 7-series primitives + 12 UniMacros + 20 XPMs.
- Surveyed XilinxUnisimLibrary (Vivado 2020.1, Verilog only, Apache-2.0); 11 UG953 primitives exist only in Vivado's retarget/ library; SERDES/IN_FIFO/OUT_FIFO wrap encrypted secureip.
- Owner Q&A: 7-series first; vector + SV + cocotb styles in parallel; pinned containers; fpgas.online use approved.
- Spec rev 1 reviewed by two sub-agents (technical; requirements/process). Rev 2 adopts: timed event-list stimulus, port classes, glbl channel, clock observers, DRP transactions, Verilator X-seed runs, fasm2bels flow detection, pad and config-primitive harnesses, clean-room golden models with provenance, behavioural-claim coverage, work units with path ownership, generated status only on main, concrete review/merge gate, reviewers count toward the 2-agent limit.
- Next: implementation plan for build-order step 1 (bootstrap) and step 2 (core infra + FDRE pilot).
