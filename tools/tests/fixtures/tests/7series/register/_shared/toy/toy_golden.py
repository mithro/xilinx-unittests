# SPDX-License-Identifier: Apache-2.0
"""ToyDff: the TOYFF fixture's golden model (xut tool tests only; TOYFF is not a real
primitive). Standard library plus ``xut_models.base`` only: the TOYFF cocotb test
imports it inside the simulator container, from this ``_shared/toy`` directory."""

from xut_models.base import Model, Out, bit_attr


class ToyDff(Model):
    PRIM = "TOYFF"
    CLOCKS = ("C",)
    OUTPUTS = {"Q": 1}

    @classmethod
    def inputs(cls) -> dict[str, int]:
        return {"C": 1, "D": 1}

    def power_on(self) -> None:
        self.q, self.gsr = bit_attr(self.attrs.get("INIT", 0)), 1

    def set_input(self, port: str, value: int) -> None:
        setattr(self, port.lower(), value)

    def clock_edge(self, port: str, rising: bool) -> None:
        if rising and not self.gsr:
            self.q = self.d
            self.hit("TOYFF.C1")

    def glbl(self, signal: str, value: int) -> None:
        self.gsr = value

    def outputs(self) -> dict[str, Out]:
        return {"Q": Out(str(self.q), "doc:1")}
