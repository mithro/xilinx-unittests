// SPDX-License-Identifier: Apache-2.0
module TOYBAD (output Q, input D);
  parameter MODE = "FAST";
  assign Q = D +;
endmodule
