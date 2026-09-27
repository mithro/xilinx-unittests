// SPDX-License-Identifier: Apache-2.0
// GSR mid-simulation test shared by the luts unit (LUT1-LUT6, LUT6_2; spec §4.3 sv style).
// The including file defines LUT_TB, LUT_N, LUT_INST and (LUT6_2) LUT_DUAL, as for
// luts_x_tb.svh. INIT is a module parameter (test.yaml configs).
// Checked (documented, the logic table): every address before GSR rises and after it falls.
// Checkpoints only (UG953 names no GSR effect on a LUT): the output when GSR rises
// (G.rise), at every address walked while it is high (G.a<n>) and when it falls (G.fall).
`timescale 1ps / 1ps
module `LUT_TB #(
    parameter [(1 << `LUT_N) - 1:0] INIT = {(1 << `LUT_N){1'b0}}
);
`include "xut_trace.svh"
  // No declaration initialiser: a combinational UNISIM model can miss one at time 0.
  // The inputs get their first value by a time-0 non-blocking update instead, as in the
  // vector testbench, after every model process is waiting.
  reg [`LUT_N-1:0] I;
  wire O;
`ifdef LUT_DUAL
  wire O5;
`endif
  `LUT_INST

  integer a;

  task automatic point(input integer n);  // G.a<n>: address n while GSR is high
    begin
      xut_open;
`ifdef LUT_DUAL
      $fdisplay(xut_fd, "G.a%0d  O6=%b O5=%b", n, O, O5);
`else
      $fdisplay(xut_fd, "G.a%0d  O=%b", n, O);
`endif
    end
  endtask

  task automatic edge_point(input reg rise);  // G.rise / G.fall
    begin
      xut_open;
`ifdef LUT_DUAL
      if (rise) $fdisplay(xut_fd, "G.rise  O6=%b O5=%b", O, O5);
      else $fdisplay(xut_fd, "G.fall  O6=%b O5=%b", O, O5);
`else
      if (rise) $fdisplay(xut_fd, "G.rise  O=%b", O);
      else $fdisplay(xut_fd, "G.fall  O=%b", O);
`endif
    end
  endtask

  task automatic check_all(input reg after);
    integer b;
    begin
      for (b = 0; b < (1 << `LUT_N); b = b + 1) begin
        I = b;
        #1000;
        if (after) begin
          `XUT_CHECKN("post.O.a", b, O, INIT[b])
        end else begin
          `XUT_CHECKN("pre.O.a", b, O, INIT[b])
        end
`ifdef LUT_DUAL
        if (after) begin
          `XUT_CHECKN("post.O5.a", b, O5, INIT[b%32])
        end else begin
          `XUT_CHECKN("pre.O5.a", b, O5, INIT[b%32])
        end
`endif
      end
    end
  endtask

  initial begin
    I <= {`LUT_N{1'b0}};
    #120000;  // past glbl's power-on GSR pulse (ROC_WIDTH, 100 ns)
    check_all(1'b0);
    I = {`LUT_N{1'b1}};
    #1000;
    glbl.GSR_int = 1'b1;
    #1000;
    edge_point(1'b1);
    for (a = 0; a < (1 << `LUT_N); a = a + 1) begin
      I = a;
      #1000;
      point(a);
    end
    glbl.GSR_int = 1'b0;
    #1000;
    edge_point(1'b0);
    check_all(1'b1);
    xut_finish;
  end
endmodule
