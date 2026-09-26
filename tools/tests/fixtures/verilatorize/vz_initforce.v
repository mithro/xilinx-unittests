// SPDX-License-Identifier: Apache-2.0
// vz_initforce.v — SRL-style initialisation: forced in an initial block and released
// once the clock settles (a polling loop that may run zero times).
`timescale 1ps/1ps
module VZINIT (output Q, input C, input D);
  reg [3:0] data = 4'h5;
  assign Q = data[3];
  initial begin
    assign data = 4'h5;
    while (C !== 1'b0) #10;
    deassign data;
  end
  always @(posedge C) data <= {data[2:0], D};
endmodule
