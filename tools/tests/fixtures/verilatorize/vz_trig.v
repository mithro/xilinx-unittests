// SPDX-License-Identifier: Apache-2.0
// vz_trig.v — several triggers, glbl.GSR among them.
`timescale 1ps/1ps
module VZTRIG (output Q, input C, input D, input CLR, input PRE);
  reg q;
  wire gsr_in = glbl.GSR;
  assign Q = q;
  always @(gsr_in or CLR or PRE)
    if (gsr_in) assign q = 1'b0;
    else if (CLR) assign q = 1'b0;
    else if (PRE) assign q = 1'b1;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
