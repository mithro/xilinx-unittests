// SPDX-License-Identifier: Apache-2.0
// vz_bad_disable.v — the correctness reviewer's VZDIS counterexample (PR #10 review, must-fix 5).
// `disable blk` leaves the block with the override still active; treating it as fall-through
// substituted X__base for the read `y = x` and silently miscompiled the R=1 path.
`timescale 1ps/1ps
module VZDIS (output Y, input R, input C, input D);
  reg x, y;
  assign Y = y;
  always @(posedge C) x <= D;
  always @(R) begin
    begin : blk
      assign x = 1'b1;
      if (R) disable blk;
      deassign x;
    end
    y = x;
  end
endmodule
