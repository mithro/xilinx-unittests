// SPDX-License-Identifier: Apache-2.0
// vz_async.v — the forced reg also has an asynchronous clear in its ordinary writer.
`timescale 1ps/1ps
module VZASYNC (output Q, input C, input D, input CLR);
  reg q;
  wire gsr_in = glbl.GSR;
  assign Q = q;
  always @(gsr_in)
    if (gsr_in) assign q = 1'b0;
    else deassign q;
  always @(posedge C or posedge CLR)
    if (CLR) q <= 1'b0;
    else q <= D;
endmodule
