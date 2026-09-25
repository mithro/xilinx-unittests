# SPDX-License-Identifier: Apache-2.0
"""Runners by name (spec §6). Each writes build/<flow>/<runner>/<model-source>/<test-id>/."""

from xut.runners.base import Runner
from xut.runners.python import PythonRunner

#: Every runner ``xut run`` can select. Later tasks add iverilog, xsim, verilator and
#: iverilog-vz (the latter only once it is implemented, so nothing selects a stub).
RUNNERS: dict[str, type[Runner]] = {"python": PythonRunner}
