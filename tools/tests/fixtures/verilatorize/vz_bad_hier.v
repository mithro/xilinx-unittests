// SPDX-License-Identifier: Apache-2.0
// vz_bad_hier.v — refusal: a signal in the trigger cone is written hierarchically from
// another module.
`timescale 1ps/1ps
module VZHIER (output Q, input C, input D, input S);
  reg r; reg en;
  assign Q = r;
  VZHIER_HLP h (.i(S));
  always @(en or S)
    if (en | S) assign r = 1'b0; else deassign r;
  always @(posedge C) r <= D;
endmodule
module VZHIER_HLP (input i);
  always @(i) VZHIER.en = i;
endmodule
