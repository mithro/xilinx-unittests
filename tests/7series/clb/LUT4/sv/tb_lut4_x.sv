// SPDX-License-Identifier: Apache-2.0
// 7series.LUT4.L1.sv_x_inputs (body: _shared/luts/luts_x_tb.svh)
`define LUT_TB tb_lut4_x
`define LUT_N 4
`define LUT_INST LUT4 #(.INIT(INIT)) dut (.O(O), .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]));
`include "luts_x_tb.svh"
