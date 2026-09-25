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
_ASYNC = frozenset({"CLR", "PRE", "PWRDWN", "GSR", "GTS"})
# (primitive, port) pairs whose control input is asynchronous (spec §5.1)
_ASYNC_ON = {
    **{p: {"BUFGCTRL"} for p in ("S0", "S1", "CE0", "CE1", "IGNORE0", "IGNORE1")},
    "S": {"BUFGMUX", "BUFGMUX_1", "BUFGMUX_CTRL"},
    "CE": {"BUFGCE", "BUFGCE_1", "BUFHCE", "BUFMRCE", "BUFR"},
    "RESET": {"XADC", "IN_FIFO", "OUT_FIFO"},
}
_RST_ASYNC_PREFIXES = ("FIFO", "MMCM", "PLL", "ISERDES", "OSERDES", "IDELAYCTRL")
# set/reset whose timing is chosen by an attribute; default class is data
_SRTYPE_DEPENDENT = {"IDDR", "IDDR_2CLK", "ODDR"}
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
        if port in _ASYNC or prim in _ASYNC_ON.get(port, ()):
            return "async"
        if port == "RST" and prim.startswith(_RST_ASYNC_PREFIXES):
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


def class_note(prim: str, port: str) -> str | None:
    """Why the default class of ``prim.port`` may be wrong for some configurations."""
    if prim in _SRTYPE_DEPENDENT and port in ("S", "R"):
        return (
            "class depends on SRTYPE (data for SYNC, async for ASYNC); "
            "needs a per-configuration override"
        )
    return None
