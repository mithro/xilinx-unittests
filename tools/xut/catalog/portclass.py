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
        "PSCLK",  # MMCME2_ADV phase-shift clock
        "CONVSTCLK",  # XADC convert-start clock
        "CLKIN",  # ODELAYE2 delayed-clock input
        "USRCCLKO",  # STARTUPE2 user clock driven onto the CCLK pin
    }
)
# (primitive, port) pairs whose name is in _CLOCKS but which are not clocks
_NOT_CLOCK_ON = {"C": {"DSP48E1"}}  # DSP48E1.C is the 48-bit C operand
# (primitive, port) pairs that output a clock (spec §5.1 clock_out)
_CLOCK_OUT_ON = {
    "CFGCLK": {"STARTUPE2", "USR_ACCESSE2"},
    "CFGMCLK": {"STARTUPE2"},
    "TCK": {"BSCANE2"},
    "DRCK": {"BSCANE2"},
    "O": {"IBUFDS_GTE2"},
    "ODIV2": {"IBUFDS_GTE2"},
}
# analog/pad inputs that are not I/IB of an IBUF*
_PAD_ON = {p: {"XADC"} for p in ("VP", "VN", "VAUXP", "VAUXN")}
# latch gate and gate enable
_GATE_ON = {p: {"LDCE", "LDPE"} for p in ("G", "GE")}
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
        if (prim.startswith("IBUF") and port in ("I", "IB")) or prim in _PAD_ON.get(port, ()):
            return "pad"
        if prim.startswith(_DRP_PREFIXES) and port in _DRP:
            return "drp"
        if prim in _GATE_ON.get(port, ()):
            return "gate"
        if port in _CLOCKS and prim not in _NOT_CLOCK_ON.get(port, ()):
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
    if port.startswith(("CLKOUT", "CLKFBOUT")) or prim in _CLOCK_OUT_ON.get(port, ()):
        return "clock_out"
    if port == "O" and _is_buf(prim):
        return "clock_out"
    return "data"


def class_note(prim: str, port: str, direction: str) -> str | None:
    """Why the default class of ``prim.port`` may be wrong, for EXTRACTION_REPORT.md's
    "Port class notes": a configuration-dependent class, or a port whose name contains
    ``CLK`` but whose default class is ``data`` (a clock select/enable/status signal,
    or a clock this module doesn't recognise — the owning unit must confirm it)."""
    if prim in _SRTYPE_DEPENDENT and port in ("S", "R"):
        return (
            "class depends on SRTYPE (data for SYNC, async for ASYNC); "
            "needs a per-configuration override"
        )
    if "CLK" in port and default_class(prim, port, direction) == "data":
        return (
            "class data despite CLK in its name (select/enable/status, not a clock); "
            "override if it is a clock"
        )
    return None
