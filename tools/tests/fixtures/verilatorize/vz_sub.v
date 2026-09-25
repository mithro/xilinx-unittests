// SPDX-License-Identifier: Apache-2.0
// vz_sub.v — the trigger is reached through a same-file sub-instance.
`timescale 1ps/1ps
module VZSUB_INV (output o, input i);
  assign o = ~i;
endmodule
module VZSUB (output Q, input C, input D, input CLR);
  wire clr_n;
  reg q;
  VZSUB_INV u (.o(clr_n), .i(CLR));
  assign Q = q;
  always @(clr_n)
    if (!clr_n) assign q = 1'b0;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
