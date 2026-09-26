// SPDX-License-Identifier: Apache-2.0
// vz_bad_nbacone.v — the release is driven by a register written with a non-blocking
// assignment, so the forcing block runs from the NBA region. The shadow-register capture is
// not order-safe there on Verilator 5.048 (reviewer's VZCE counterexample, ruling S28).
`timescale 1ps/1ps
module VZCE (output [3:0] Q, input C, input D, input R);
  reg [3:0] q;
  reg r;
  assign Q = q;
  always @(posedge C) r <= R;
  always @(r)
    if (r) assign q = 4'ha;
    else deassign q;
  always @(posedge C) begin
    q[0] <= D;
    q[3:1] <= {q[2:0]};
  end
  always @(negedge C) q[2] <= ~D;
endmodule
