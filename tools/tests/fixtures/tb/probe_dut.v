// SPDX-License-Identifier: Apache-2.0
// Testbench probe (no UNISIM): observes how xut_vector_tb drives in_vec and clk.
`timescale 1ps / 1ps
module xut_dut (input wire [0:0] clk, input wire [3:0] in_vec, output wire [5:0] out_vec);
  // out_vec[0]   in_vec[1:0] was once seen at 01 or 10: a co-timed change of both
  //              bits (00 <-> 11) was not applied atomically
  // out_vec[3:1] rising clk[0] edges seen, modulo 8
  // out_vec[4]   combinational copy of in_vec[2]: stays x unless the testbench's
  //              time-0 values reach processes that are already waiting
  // out_vec[5]   in_vec[3] as captured by the last rising clk[0] edge
  reg mid = 1'b0, cap = 1'b0;
  reg [2:0] cnt = 3'd0;
  reg comb;
  always @(in_vec[1:0]) if (in_vec[1] !== in_vec[0]) mid = 1'b1;
  always @(in_vec[2]) comb = in_vec[2];
  always @(posedge clk[0]) begin
    cnt <= cnt + 3'd1;
    cap <= in_vec[3];
  end
  assign out_vec = {cap, comb, cnt, mid};
endmodule
module glbl;
  reg GSR_int = 1'b1, GTS_int = 1'b0, GRESTORE_int = 1'b0;
  wire GSR = GSR_int;
  initial #100000 GSR_int = 1'b0;
endmodule
