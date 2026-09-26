// SPDX-License-Identifier: Apache-2.0
// vz_ranges.v — forced regs with non-[n:0] packed ranges and signedness, read through
// selects: the override nets must index exactly as the regs did.
`timescale 1ps/1ps
module VZRANGE (output QA, output [1:0] QB, output QC, output [7:0] CV,
                input C, input D, input R, input [3:0] V);
  reg [4:1] a;
  reg [0:3] b;
  reg signed [7:0] c;
  assign QA = a[4];
  assign QB = b[0:1];
  assign QC = c[7];
  assign CV = c >>> 1;
  always @(R)
    if (R) begin
      assign a = V;
      assign b = V;
      assign c = -2'sd1;
    end
    else begin
      deassign a;
      deassign b;
      deassign c;
    end
  always @(posedge C) begin
    a <= {a[3:1], D};
    b <= {D, b[0:2]};
    c <= {c[6:0], D};
  end
endmodule
