// SPDX-License-Identifier: Apache-2.0
// vz_helper.v — the forcing is in a same-file helper module (FIFO18E1-style); its trigger
// port is fed by a registered stage in the parent.
`timescale 1ps/1ps
module VZHELPER_CORE (Q, C, D, RST_I);
  output Q;
  input C, D, RST_I;
  reg q;
  assign Q = q;
  always @(RST_I)
    if (RST_I) assign q = 1'b0;
    else deassign q;
  always @(posedge C) q <= D;
endmodule
module VZHELPER (output Q, input C, input D, input RST, input PWR);
  reg rst_q;
  always @(posedge C or posedge PWR)
    if (PWR) rst_q <= 1'b1;
    else rst_q <= RST;
  VZHELPER_CORE u (.Q(Q), .C(C), .D(D), .RST_I(rst_q));
endmodule
