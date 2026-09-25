// SPDX-License-Identifier: Apache-2.0
// vz_loopwait.v — BUFGCE_DIV-style forcing block: an `always` loop whose event control is
// the last statement of its body; forcing integer and ranged regs.
`timescale 1ps/1ps
module VZLOOPWAIT (output [3:0] Q, output [31:0] N, input C, input D, input S);
  reg signed [4:1] r;
  integer cnt;
  wire s_in = S;
  assign Q = r;
  assign N = cnt;
  always begin
    if (s_in == 1'b1) begin
      assign r = 4'b0;
      assign cnt = 0;
    end
    else if (s_in == 1'b0) begin
      deassign r;
      deassign cnt;
    end
    @(s_in);
  end
  always @(posedge C) begin
    r <= {r[3:1], D};
    cnt = cnt + 1;
  end
endmodule
