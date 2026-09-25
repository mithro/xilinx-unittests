// SPDX-License-Identifier: Apache-2.0
`timescale 1 ps / 1 ps
module TOYLOC (O, I);
  parameter LOC = "UNPLACED";
  parameter MSGON = "TRUE";
  parameter XON = "TRUE";
  parameter MODE = "FAST";
  output O;
  input I;
  tri0 glblGSR = glbl.GSR;
  assign O = I & ~glblGSR;
endmodule
