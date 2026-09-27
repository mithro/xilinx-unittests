// SPDX-License-Identifier: Apache-2.0
// 7series.LUT3.L1.sv_x_inputs (body: _shared/luts/luts_x_tb.svh)
`define LUT_TB tb_lut3_x
`define LUT_N 3
`define LUT_INST LUT3 #(.INIT(INIT)) dut (.O(O), .I0(I[0]), .I1(I[1]), .I2(I[2]));
`include "luts_x_tb.svh"
