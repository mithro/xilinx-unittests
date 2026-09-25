// SPDX-License-Identifier: Apache-2.0
// vz_ifelse.v — the deassign is the then-arm of an if/else (dangling-else guard).
`timescale 1ps/1ps
module VZIFELSE (output Q, input C, input D, input C2, input E);
  reg q;
  assign Q = q;
  always @(C2 or E)
    if (C2) deassign q;
    else assign q = E;
  always @(posedge C) q <= D;
endmodule
