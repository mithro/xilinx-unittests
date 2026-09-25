// SPDX-License-Identifier: Apache-2.0
`timescale 1ps / 1ps
module xut_dut (input wire [0:0] clk, input wire [2:0] in_vec, output wire [0:0] out_vec);
  // in_vec: [0]=D [1]=CLR(async) [2]=unused
  reg q;
  always @(posedge clk[0] or posedge in_vec[1] or posedge glbl.GSR)
    if (glbl.GSR) q <= 1'b1;
    else if (in_vec[1]) q <= 1'b0;
    else q <= in_vec[0];
  assign out_vec[0] = q;
endmodule
module glbl;
  // GSR rises at 1 ps (a definite posedge) and falls at ROC_WIDTH = 100 ns, like glbl.v.
  reg GSR_int = 1'b0, GTS_int = 1'b0, GRESTORE_int = 1'b0;
  wire GSR = GSR_int;
  initial begin
    #1 GSR_int = 1'b1;
    #99999 GSR_int = 1'b0;
  end
endmodule
