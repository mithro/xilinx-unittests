// SPDX-License-Identifier: Apache-2.0
// vz_zcmp.v — inputs defaulted by z-compares (ruling S38): both operand orders, !==,
// bit selects, an async control. No procedural assign: only the z-compare rewrite applies.
`timescale 1ps/1ps
module VZZCMP (output Q, output [1:0] O, input C, input CE, input R, input D, input [1:0] S,
               input CLR);
  reg q = 1'b0;
  wire ce_en = CE || (CE === 1'bz);
  always @(posedge C or posedge CLR)
    if (CLR && (CLR !== 1'bz)) q <= 1'b0;
    else if ((R !== 1'bz) && R) q <= 1'b0;
    else if (ce_en) q <= D;
  assign Q = q;
  assign O[0] = (1'bz === S[0]) ? 1'b1 : S[0];
  assign O[1] = (S[1] !== 1'bz) ? S[1] : 1'b0;
endmodule
