// SPDX-License-Identifier: Apache-2.0
// glbl.v — the toy glbl module of tools/tests/fixtures/tb/toy_dut.v (Task 7).
`timescale 1ps / 1ps
module glbl;
  // GSR rises at 1 ps (a definite posedge) and falls at ROC_WIDTH = 100 ns, like glbl.v.
  reg GSR_int = 1'b0, GTS_int = 1'b0, GRESTORE_int = 1'b0;
  wire GSR = GSR_int;
  initial begin
    #1 GSR_int = 1'b1;
    #99999 GSR_int = 1'b0;
  end
endmodule
