// SPDX-License-Identifier: Apache-2.0
// vz_bad_self.v — refusal: the override expression reads the forced reg itself.
`timescale 1ps/1ps
module VZSELF (output Q, input C, input D, input S);
  reg r;
  assign Q = r;
  always @(S)
    if (S) assign r = ~r;
    else deassign r;
  always @(posedge C) r <= D;
endmodule
