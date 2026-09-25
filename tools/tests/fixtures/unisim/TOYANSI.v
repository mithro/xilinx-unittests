// SPDX-License-Identifier: Apache-2.0
`timescale 1 ps / 1 ps
module TOYANSI #(
  `ifdef XIL_TIMING
  parameter LOC = "UNPLACED",
  `endif
  parameter [0:0] INIT = 1'b1,
  parameter IOSTANDARD = "DEFAULT",
  parameter integer DEPTH = 4,
  parameter real PERIOD = 10.0
)(
  output Q,
  input [3:0] D,
  inout IO
);
  localparam HIDDEN = 3;
  assign Q = D[0];
endmodule
