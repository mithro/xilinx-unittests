// SPDX-License-Identifier: Apache-2.0
// vz_constvar.v — a variable in the trigger cone that is never written (PLLE2_ADV-style):
// it is a constant, not an unresolved driver.
`timescale 1ps/1ps
module VZCONST (output Q, input C, input D, input S);
  integer never;
  reg r;
  assign Q = r;
  always @(S or never)
    if (S || never > 0) assign r = 1'b0;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
