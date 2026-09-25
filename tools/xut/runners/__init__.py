# SPDX-License-Identifier: Apache-2.0
"""Runners by name (spec §6). Each writes build/<flow>/<runner>/<model-source>/<test-id>/."""

from xut.runners.base import Runner
from xut.runners.iverilog import IverilogRunner
from xut.runners.python import PythonRunner
from xut.runners.xsim import XsimRunner

#: Every runner ``xut run`` can select. Later tasks add verilator and iverilog-vz (the
#: latter only once it is implemented, so nothing selects its stub).
RUNNERS: dict[str, type[Runner]] = {
    "python": PythonRunner,
    "xsim": XsimRunner,
    "iverilog": IverilogRunner,
}
