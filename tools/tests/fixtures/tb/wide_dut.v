// SPDX-License-Identifier: Apache-2.0
// Testbench probe (no UNISIM): a 100-bit in_vec and out_vec, so the operation words,
// the testbench's vectors and raw_to_trace are exercised far past 32/64 bits.
`timescale 1ps / 1ps
module xut_dut (input wire [0:0] clk, input wire [99:0] in_vec, output reg [99:0] out_vec);
  always @(posedge clk[0]) out_vec <= in_vec;  // x until the first rising edge
endmodule
module glbl;
  reg GSR_int = 1'b1, GTS_int = 1'b0, GRESTORE_int = 1'b0;
  wire GSR = GSR_int;
  initial #100000 GSR_int = 1'b0;
endmodule
