// SPDX-License-Identifier: Apache-2.0
// 7series.LUT1.L1.sv_x_inputs (body: _shared/luts/luts_x_tb.svh)
`define LUT_TB tb_lut1_x
`define LUT_N 1
`define LUT_INST LUT1 #(.INIT(INIT)) dut (.O(O), .I0(I[0]));
`include "luts_x_tb.svh"
