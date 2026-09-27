// SPDX-License-Identifier: Apache-2.0
// 7series.LUT6.L1.sv_gsr_midsim (body: _shared/luts/luts_gsr_tb.svh)
`define LUT_TB tb_lut6_gsr
`define LUT_N 6
`define LUT_INST LUT6 #(.INIT(INIT)) dut (.O(O), .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4]), .I5(I[5]));
`include "luts_gsr_tb.svh"
