// SPDX-License-Identifier: Apache-2.0
// 7series.LUT2.L1.sv_gsr_midsim (body: _shared/luts/luts_gsr_tb.svh)
`define LUT_TB tb_lut2_gsr
`define LUT_N 2
`define LUT_INST LUT2 #(.INIT(INIT)) dut (.O(O), .I0(I[0]), .I1(I[1]));
`include "luts_gsr_tb.svh"
