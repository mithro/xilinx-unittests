// SPDX-License-Identifier: Apache-2.0
// vz_gate.v — triggers reached only through gate primitives.
`timescale 1ps/1ps
module BUFVZ (output O, input I, input CLR);
  wire gsr_in_raw = glbl.GSR;
  wire clr_in, gsr_n, gsr_in;
  reg o;
  buf b0 (clr_in, CLR);
  not n0 (gsr_n, gsr_in_raw);
  and a0 (gsr_in, ~gsr_n, 1'b1);
  assign O = o;
  always @(gsr_in or clr_in)
    if (gsr_in || clr_in) assign o = 1'b0;
    else deassign o;
  always @(I) o = I;
endmodule
