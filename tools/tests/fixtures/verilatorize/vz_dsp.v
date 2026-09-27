// SPDX-License-Identifier: Apache-2.0
// vz_dsp.v — the DSP48-over-DSP48E1 shape (PR #10 review, must-fix 2): the parent needs no
// rewrite, but instantiates its transformed child with AREG=0, a parameterisation other than
// the child's default. The child's own verdict for AREG=0 must gate the parent (ruling S50).
`timescale 1ps/1ps
module VZDSP #(parameter [0:0] INIT = 1'b0) (output Q, input C, input CE, input D);
  VZDSPE1 #(.AREG(0), .INIT(INIT)) u (.Q(Q), .C(C), .CE(CE), .D(D));
endmodule
