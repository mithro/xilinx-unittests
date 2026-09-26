# SPDX-License-Identifier: Apache-2.0
"""Runners by name (spec §6). Each writes build/<flow>/<runner>/<model-source>/<test-id>/."""

from xut.runners.base import Runner
from xut.runners.iverilog import IverilogRunner
from xut.runners.python import PythonRunner
from xut.runners.verilator import IverilogVzRunner, VerilatorRunner
from xut.runners.xsim import XsimRunner

#: Every runner ``xut run`` can select. ``iverilog-vz`` guards the Verilator results (spec
#: §6.2): ``xut.run.run_tests`` adds it whenever ``verilator`` is selected.
RUNNERS: dict[str, type[Runner]] = {
    "python": PythonRunner,
    "xsim": XsimRunner,
    "iverilog": IverilogRunner,
    "verilator": VerilatorRunner,
    "iverilog-vz": IverilogVzRunner,
}
