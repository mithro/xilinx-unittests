// SPDX-License-Identifier: Apache-2.0
// vz_guard.v — the rev-3.1 deassign guard: the forcing block's control S goes x->0 at
// t=0, so it runs `deassign q` while q is not forced. In Verilog that deassign is a no-op
// and q keeps its initial 1; a capture without the guard would load the override value 0.
`timescale 1ps/1ps
module VZGUARD (output Q, input S);
  reg q;
  assign Q = q;
  initial q = 1'b1;
  always @(S)
    if (S) assign q = 1'b0;
    else deassign q;
endmodule
