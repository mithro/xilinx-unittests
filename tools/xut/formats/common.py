# SPDX-License-Identifier: Apache-2.0
"""The name grammar and error base shared by ``.xvec``, ``.xtr`` and their producers.

One grammar, used by the parsers, the writers, ``xut wrap`` (configuration names) and
``xut.stimgen.VecBuilder`` (sample labels), so a name one of them accepts can never be
read back differently by another:

- a *label* (``.xvec`` ``sample`` label, ``.xtr`` sample label) is
  ``[A-Za-z0-9_./-]+``;
- a *configuration name* is a label without ``/``: ``xut.formats.xtr.concat`` joins
  ``<cfg>/<label>``, so the first ``/`` must always end the configuration name;
- a *port* name (``.xtr`` value and provenance tokens) is a Verilog simple identifier,
  ``[A-Za-z_][A-Za-z0-9_$]*``;
- a *header key* is ``[A-Za-z_][A-Za-z0-9_.]*`` (``attr.INIT``).

Standard library only (``xut.errors`` is itself stdlib-only), because the formats are
imported inside the simulator container.
"""

from __future__ import annotations

import re

from xut.errors import XutError

LABEL = re.compile(r"[A-Za-z0-9_./-]+")
CFG = re.compile(r"[A-Za-z0-9_.-]+")
PORT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
HEADER_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


class FormatError(XutError, ValueError):
    """A stimulus or trace that is malformed or cannot be represented, with the 1-based
    line number when it comes from a file. The CLI shows it as a clean ``Error:``."""

    def __init__(self, msg: str, line: int | None = None) -> None:
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


def is_label(s: object) -> bool:
    return isinstance(s, str) and LABEL.fullmatch(s) is not None


def is_cfg(s: object) -> bool:
    return isinstance(s, str) and CFG.fullmatch(s) is not None


def is_port(s: object) -> bool:
    return isinstance(s, str) and PORT.fullmatch(s) is not None


def is_header_key(s: object) -> bool:
    return isinstance(s, str) and HEADER_KEY.fullmatch(s) is not None
