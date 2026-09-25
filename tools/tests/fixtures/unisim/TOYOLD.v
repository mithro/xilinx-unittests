// SPDX-License-Identifier: Apache-2.0
`timescale 1 ps / 1 ps
module TOYOLD (DO, ADDR, CLK);
  parameter integer DOA_REG = 0;
  parameter [255:0] INIT_00 = 256'h0;
  output [15:0] DO;
  input [13:0] ADDR;
  input CLK;
  assign DO = 16'h0;
endmodule
