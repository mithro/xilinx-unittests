# SPDX-License-Identifier: Apache-2.0
"""What a primitive's results depend on in the repository, and its git state (review
(b) #2, ruling S21).

``xut run`` writes the ``tree_hash``, ``head`` and ``dirty`` of the tested primitive
into every ``result.json``; ``xut status record`` refuses a result whose ``tree_hash``
is not the current one or that was measured on a dirty tree. Both use the one
definition here.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xut.testspec import TestCase


def tree_paths(family: str, group: str, prim: str, unit: str) -> list[str]:
    """The unit-owned inputs of ``prim``'s results: its tests, its unit's shared test
    code, its golden model (per primitive and the unit's ``_common``) and its catalog
    overrides (the claims).

    Not included: the generated ``catalog/<family>/<PRIM>.yaml`` (the python run reads
    its polarity levels), ``tools/xut`` and any model helper outside
    ``_common/<unit>.py``; the tools are recorded separately, in ``measured.tools``.
    A path absent from HEAD contributes nothing, so a primitive with none of these
    committed hashes to the empty-input constant ``sha256:e3b0c442...``; harmless,
    because ``xut status record`` needs a committed test.yaml."""
    return [
        f"tests/{family}/{group}/{prim}",
        f"tests/{family}/{group}/_shared/{unit}",
        f"models/xut_models/{family}/{prim.lower()}.py",
        f"models/xut_models/{family}/_common/{unit}.py",
        f"catalog/{family}/{prim}.overrides.yaml",
    ]


@dataclass(frozen=True)
class TreeState:
    #: ``"sha256:<hex>"`` over the sorted lines ``"<path> <object id of HEAD:./<path>>"``
    #: of the paths that exist in HEAD; ``None`` outside a git checkout.
    tree_hash: str | None
    #: ``git rev-parse HEAD``; ``None`` outside a git checkout.
    head: str | None
    #: ``git status --porcelain -- <paths>`` lines (uncommitted or untracked inputs);
    #: ``None`` outside a git checkout.
    dirty: list[str] | None


def _git(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, input=stdin)
    except (FileNotFoundError, NotADirectoryError):
        return None


def head(root: Path) -> str | None:
    """``git rev-parse HEAD`` (the full SHA) of ``root``; ``None`` outside a checkout."""
    r = _git(Path(root), "rev-parse", "--verify", "--quiet", "HEAD")
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip() or None


def tree_state(root: Path, paths: list[str]) -> TreeState:
    """The git state of ``paths`` under ``root`` (all fields ``None`` if git fails), in
    three git calls: HEAD, ``status`` and one ``cat-file --batch-check`` for every
    path's object id (the same ids ``git rev-parse HEAD:./<path>`` gives)."""
    root = Path(root)
    sha = head(root)
    st = _git(root, "status", "--porcelain", "--", *paths)
    if sha is None or st is None or st.returncode != 0:
        return TreeState(None, None, None)
    # ``<sha>:./<p>`` is relative to ``root``, which may be below the checkout's top
    ids = _git(
        root,
        "cat-file",
        "--batch-check=%(objectname)",
        stdin="".join(f"{sha}:./{p}\n" for p in paths),
    )
    if ids is None or ids.returncode != 0:
        return TreeState(None, None, None)
    out = ids.stdout.splitlines()
    if len(out) != len(paths):
        return TreeState(None, None, None)
    lines = [
        f"{p} {oid}" for p, oid in zip(paths, out, strict=True) if not oid.endswith(" missing")
    ]
    text = "".join(f"{line}\n" for line in sorted(lines))
    return TreeState(
        "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        sha,
        [line.strip() for line in st.stdout.splitlines() if line.strip()],
    )


def case_state(case: TestCase, cache: dict | None = None) -> TreeState:
    """``tree_state`` of the primitive ``case`` tests, from its own repository root
    (``<root>/tests/<family>/<group>/<PRIM>``). With ``cache`` (one ``xut run``'s,
    ``RunContext.provenance``), each primitive's state is computed once per run: a
    run's results are one measurement of one tree."""
    root = case.test_dir.parents[3]
    paths = tree_paths(case.family, case.group, case.prim, case.work_unit)
    if cache is None:
        return tree_state(root, paths)
    key = (str(root), tuple(paths))
    if key not in cache:
        cache[key] = tree_state(root, paths)
    return cache[key]
