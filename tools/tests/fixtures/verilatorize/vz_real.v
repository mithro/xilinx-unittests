// SPDX-License-Identifier: Apache-2.0
// vz_real.v — a forced real variable (MMCM-style fractional divider value).
`timescale 1ps/1ps
module VZREAL (output [31:0] Q, input C, input S);
  real rv;
  assign Q = $rtoi(rv);
  always @(S)
    if (S) assign rv = 1.5;
    else deassign rv;
  always @(posedge C) rv = rv + 1.0;
endmodule
