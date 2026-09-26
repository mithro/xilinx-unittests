# SPDX-License-Identifier: Apache-2.0
"""Read one ``build/<flow>/<runner>/<model-source>/<test-id>/result.json`` (spec §6, §14).

The one reader of ``xut crosscheck`` and ``xut status record``: a result is used only
when it parses, validates against ``result.schema.json`` and names the path it sits
at. Anything else is *unusable*, and both consumers treat it as an ``error`` result
with the reason given here, never as a traceback and never as evidence.

A ``pass`` or ``fail`` must also carry evidence: at least one configuration that ran
(``pass``/``fail``). ``xut run`` never writes one without (no configurations is an
error there), so a result that does is unusable too (review (b) #2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from xut import schemas

#: Configuration statuses that ran (their samples are evidence and may be compared).
RAN = ("pass", "fail")


@dataclass(frozen=True)
class ResultFile:
    """``data`` is the parsed result.json (``{}`` when it did not parse); ``problem``
    is ``None`` for a usable result, else why it cannot be used."""

    data: dict
    problem: str | None = None


def result_dir(root: Path, flow: str, runner: str, ms: str, test_id: str) -> Path:
    return Path(root) / "build" / flow / runner / ms / test_id


def read_result(d: Path, flow: str, runner: str, ms: str, test_id: str) -> ResultFile | None:
    """``d/result.json`` for the key ``(flow, runner, ms, test_id)``; ``None`` if absent."""
    p = Path(d) / "result.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return ResultFile({}, f"unreadable result.json: {e}")
    if not isinstance(data, dict):
        return ResultFile({}, "result.json is not an object")
    try:
        schemas.validate(data, "result")
    except jsonschema.ValidationError as e:
        where = e.json_path
        return ResultFile(data, f"invalid result.json ({where}): {e.message}")
    got = (data["flow"], data["runner"], data["model_source"], data["test_id"])
    if got != (flow, runner, ms, test_id):
        return ResultFile(data, f"result.json names {got}, not its path {d}")
    if data["status"] in RAN and not any(c["status"] in RAN for c in data["configs"]):
        return ResultFile(data, f"reported {data['status']} but ran no configuration: no evidence")
    return ResultFile(data)
