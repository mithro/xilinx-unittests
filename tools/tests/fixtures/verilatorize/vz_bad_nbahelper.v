// SPDX-License-Identifier: Apache-2.0
// vz_bad_nbahelper.v — the correctness reviewer's VZNBASUB counterexample (PR #10 review,
// must-fix 1): the release is driven by an NBA-written reg inside a same-file helper instance,
// so the forcing block runs from the NBA region exactly as in vz_bad_nbacone.v (ruling S28).
`timescale 1ps/1ps
module VZNBASUB (output Q, input C, input D, input R);
  reg q;
  wire rq;
  assign Q = q;
  vznba_stage st (.y(rq), .c(C), .a(R));
  always @(posedge C) q <= D;
  always @(rq)
    if (rq) assign q = 1'b0;
    else deassign q;
endmodule
module vznba_stage (output y, input c, input a);
  reg r;
  assign y = r;
  always @(posedge c) r <= a;
endmodule
