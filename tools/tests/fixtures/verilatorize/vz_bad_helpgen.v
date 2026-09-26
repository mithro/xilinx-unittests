// SPDX-License-Identifier: Apache-2.0
// vz_bad_helpgen.v — refusal: a helper generate branch (driving the trigger cone) that no
// configuration elaborates, because the helper parameter M is not a model parameter.
`timescale 1ps/1ps
module VZG3 (output Q, input C, input D, input S, input T);
  parameter MODE = "A";
  VZG3_HLP #(.M(MODE)) h (.q(Q), .c(C), .d(D), .s(S), .t(T));
endmodule
module VZG3_HLP (output q, input c, input d, input s, input t);
  parameter M = "A";
  reg r; wire en;
  assign q = r;
  generate if (M == "B") begin : gb
    assign en = t;
  end else begin : ga
    assign en = s;
  end endgenerate
  always @(en)
    if (en) assign r = 1'b0; else deassign r;
  always @(posedge c) r <= d;
endmodule
