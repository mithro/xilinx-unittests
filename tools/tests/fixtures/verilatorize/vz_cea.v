// SPDX-License-Identifier: Apache-2.0
// vz_cea.v — an NBA-triggered assign that is never deassigned (ruling S29(1), the Task 13
// re-review's probe VZCEA): the forcing block wakes on r, a register written by a
// non-blocking assignment, so it runs from the NBA region. Without a deassign there is no
// blocking capture into the shadow register, so the transform accepts it (IDELAYE2 family).
// N counts events on q[0]: a zero-width glitch of q[0] inside one time step can change the
// count on some simulators; the equivalence check compares sampled values only (S29).
`timescale 1ps/1ps
module VZCEA (output [3:0] Q, output [7:0] N, input C, input D, input R);
  reg [3:0] q;
  reg r;
  reg [7:0] n = 8'd0;
  assign Q = q;
  assign N = n;
  always @(posedge C) r <= R;
  always @(r)
    if (r) assign q = 4'ha;
  always @(posedge C) q <= {q[2:0], D};
  always @(q[0]) n = n + 8'd1;
endmodule
