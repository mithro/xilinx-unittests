// SPDX-License-Identifier: Apache-2.0
// vz_dspe1.v — the child of vz_dsp.v: a z-compare model (ruling S38) with a register stage
// that AREG selects, like DSP48E1's A input register.
`timescale 1ps/1ps
module VZDSPE1 #(parameter integer AREG = 1, parameter [0:0] INIT = 1'b0)
  (output Q, input C, input CE, input D);
  reg q = INIT;
  reg a = 1'b0;
  always @(posedge C) if (CE || (CE === 1'bz)) a <= D;
  always @(posedge C) q <= (AREG == 1) ? a : D;
  assign Q = q;
endmodule
