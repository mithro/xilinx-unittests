// SPDX-License-Identifier: Apache-2.0
// 7series.LUT6_2.L1.sv_gsr_midsim (body: _shared/luts/luts_gsr_tb.svh)
`define LUT_TB tb_lut6_2_gsr
`define LUT_N 6
`define LUT_DUAL
`define LUT_INST LUT6_2 #(.INIT(INIT)) dut (.O6(O), .O5(O5), .I0(I[0]), .I1(I[1]), .I2(I[2]), .I3(I[3]), .I4(I[4]), .I5(I[5]));
`include "luts_gsr_tb.svh"
