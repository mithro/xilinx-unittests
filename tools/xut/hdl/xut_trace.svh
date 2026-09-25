// SPDX-License-Identifier: Apache-2.0
// Checkpoint trace + self-check helpers for hand-written SV testbenches (spec §4.3).
// Include inside the module body. Lines written: "<label>  <port>=<bits>" (.xtr body).
// xut_finish prints "XUT_CHECKS <n>" (checks executed) then XUT_PASS/XUT_FAIL; the
// runner's sv_check needs >= 1 check AND >= 1 checkpoint for a pass (ruling S15).
// trace.body is opened lazily by the first checkpoint, so a checkpoint at time 0 cannot
// race an initial block that opens it.
`ifndef XUT_TRACE_SVH
`define XUT_TRACE_SVH
`define XUT_CHECK(label, sig, exp) \
  begin \
    xut_checks = xut_checks + 1; \
    if ((sig) !== (exp)) begin \
      xut_errors = xut_errors + 1; \
      $display("XUT_FAIL %s: got %b expected %b at %0t", label, sig, exp, $time); \
    end \
  end
`define XUT_CHECKN(label, n, sig, exp) \
  begin \
    xut_checks = xut_checks + 1; \
    if ((sig) !== (exp)) begin \
      xut_errors = xut_errors + 1; \
      $display("XUT_FAIL %s%0d: got %b expected %b at %0t", label, n, sig, exp, $time); \
    end \
  end
`define XUT_POINT1(label, p1, s1) \
  begin \
    xut_open; \
    $fdisplay(xut_fd, "%s  %s=%b", label, p1, s1); \
  end
`define XUT_POINT2(label, p1, s1, p2, s2) \
  begin \
    xut_open; \
    $fdisplay(xut_fd, "%s  %s=%b %s=%b", label, p1, s1, p2, s2); \
  end
`endif
integer xut_fd = 0;  // 0: trace.body not opened yet
integer xut_errors = 0;
integer xut_checks = 0;  // XUT_CHECK/XUT_CHECKN executed: a pass needs >= 1 (ruling S15)
`ifdef XUT_GLBL_INSTANCE
// Fallback for Verilator (Task 15, Step 1): glbl as an instance of the testbench, found
// by UNISIM's upward name lookup and by this testbench's own glbl.GSR_int writes. (A
// line comment must not START with the word Verilator: Verilator parses it as a pragma.)
glbl glbl ();
`endif
task automatic xut_open;
  begin
    if (xut_fd == 0) xut_fd = $fopen("trace.body", "w");
  end
endtask
task automatic xut_finish;
  begin
    if (xut_fd != 0) $fclose(xut_fd);
    $display("XUT_CHECKS %0d", xut_checks);
    if (xut_errors == 0) $display("XUT_PASS");
    else $display("XUT_FAIL %0d check(s) failed", xut_errors);
    $finish;
  end
endtask
