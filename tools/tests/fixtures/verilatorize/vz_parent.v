// SPDX-License-Identifier: Apache-2.0
// vz_parent.v — needs no rewrite itself, but instantiates VZCHILD, which does (ruling S45):
// its Verilator results must be gated on the hierarchy's equivalence.
`timescale 1ps/1ps
module VZPARENT #(parameter [0:0] INIT = 1'b0) (output Q, input C, input CE, input D);
  VZCHILD #(.INIT(INIT)) u (.Q(Q), .C(C), .CE(CE), .D(D));
endmodule
