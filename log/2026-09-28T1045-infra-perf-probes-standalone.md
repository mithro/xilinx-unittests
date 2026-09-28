# infra/perf-probes: the xelab -generic_top probes run standalone

## What changed

- `tools/tests/test_runner_xsim.py::_xelab`, the helper of the six
  `test_xelab_generic_top_*` probes, now runs the probe the way the runner
  does since #17: `xelab --standalone` and the runner's `STANDALONE_RUN`, in
  place of `xsim snap -R`, the Tcl shell.
- The probes' assertions are unchanged. They check what xelab does with each
  `-generic_top` literal, and the elaboration is the same.

## Results

`pytest -p no:randomly --durations=6 tools/tests/test_runner_xsim.py -k
xelab_generic`, serial, in a capped scope under the heavy lock:

| | Per probe | Total |
|---|---|---|
| Before | 9.4–10.1 s | 52.6 s |
| After | 5.3–5.5 s | 31.2 s |

All 6 passed both times. The unknown-name probe stops at xelab and takes
3.6 s either way.
