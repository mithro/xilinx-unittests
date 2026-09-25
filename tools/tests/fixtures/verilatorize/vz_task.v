// SPDX-License-Identifier: Apache-2.0
// vz_task.v — the ordinary write to the forced reg is in a task body.
`timescale 1ps/1ps
module VZTASK (output Q, input C, input D, input R);
  reg r;
  assign Q = r;
  task load;
    input val;
    begin
      r = val;
    end
  endtask
  always @(R)
    if (R) assign r = 1'b0;
    else deassign r;
  always @(posedge C) load(D);
endmodule
