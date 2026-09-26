// SPDX-License-Identifier: Apache-2.0
// vz_bad_looptask.v — refusal: the assign is inside a task called in a loop, so the read
// at the top of the loop body sees a different override on the first iteration.
`timescale 1ps/1ps
module VZLOOPT (output Q, output Y, input C, input D, input S);
  reg r; reg y; integer i;
  assign Q = r; assign Y = y;
  task frc; begin assign r = 1'b0; end endtask
  always @(S) begin
    for (i = 0; i < 2; i = i + 1) begin
      y = r;
      frc;
    end
    deassign r;
  end
  always @(posedge C) r <= D;
endmodule
