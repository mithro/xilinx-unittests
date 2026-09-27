// SPDX-License-Identifier: Apache-2.0
// One byte of CRC-32 (IEEE 802.3, reflected, polynomial 0xEDB88320): the same CRC as
// Python's zlib.crc32. Keep the state starting at 32'hFFFFFFFF; the CRC is ~state.
function [31:0] xut_crc32_byte(input [31:0] crc, input [7:0] b);
  integer i;
  reg [31:0] c;
  begin
    c = crc ^ {24'h000000, b};
    for (i = 0; i < 8; i = i + 1)
      c = c[0] ? ((c >> 1) ^ 32'hEDB88320) : (c >> 1);
    xut_crc32_byte = c;
  end
endfunction
