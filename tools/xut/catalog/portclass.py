# SPDX-License-Identifier: Apache-2.0
"""Default port classes (spec §5.1). Overridable per port in <PRIM>.overrides.yaml."""

CLASSES = ("clock", "async", "gate", "data", "inout", "clock_out", "pad", "drp")

_CLOCKS = frozenset(
    {
        "C",
        "CLK",
        "CLKARDCLK",
        "CLKBWRCLK",
        "RDCLK",
        "WRCLK",
        "CLKIN1",
        "CLKIN2",
        "CLKFBIN",
        "CLKDIV",
        "CLKB",
        "OCLK",
        "OCLKB",
        "CLKDIVP",
        "DCLK",
        "REFCLK",
        "C0",
        "C1",
        "WCLK",
    }
)
_ASYNC = frozenset({"CLR", "PRE", "S0", "S1", "CE0", "CE1", "PWRDWN", "GSR", "GTS"})
_RST_ASYNC_PREFIXES = ("FIFO", "MMCM", "PLL", "ISERDES", "OSERDES")
_DRP = frozenset({"DADDR", "DI", "DO", "DEN", "DWE", "DRDY"})
_DRP_PREFIXES = ("MMCM", "PLL", "XADC")


def _is_buf(prim: str) -> bool:
    return prim.startswith("BUF")  # BUFG*, BUFH*, BUFIO, BUFMR*, BUFR


def default_class(prim: str, port: str, direction: str) -> str:
    """Return the default §5.1 class of ``prim.port``."""
    if direction == "inout":
        return "inout"
    if direction == "input":
        if prim.startswith("IBUF") and port in ("I", "IB"):
            return "pad"
        if prim.startswith(_DRP_PREFIXES) and port in _DRP:
            return "drp"
        if prim in ("LDCE", "LDPE") and port == "G":
            return "gate"
        if port in _CLOCKS:
            return "clock"
        if port in ("I0", "I1") and prim.startswith(("BUFGCTRL", "BUFGMUX")):
            return "clock"
        if port == "I" and _is_buf(prim):
            return "clock"
        if port in _ASYNC:
            return "async"
        if port == "RST" and prim.startswith(_RST_ASYNC_PREFIXES):
            return "async"
        if port in ("IGNORE0", "IGNORE1") and prim.startswith("BUFGCTRL"):
            return "async"
        return "data"
    # outputs
    if prim.startswith("OBUF") and port in ("O", "OB"):
        return "pad"
    if prim.startswith(_DRP_PREFIXES) and port in _DRP:
        return "drp"
    if port.startswith(("CLKOUT", "CLKFBOUT")):
        return "clock_out"
    if port == "O" and _is_buf(prim):
        return "clock_out"
    return "data"
