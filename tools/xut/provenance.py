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
    """Every repository path ``prim``'s results depend on: its tests, its unit's shared
    test code, its golden model (per primitive and the unit's ``_common``) and its
    catalog overrides (the claims)."""
    return [
        f"tests/{family}/{group}/{prim}",
        f"tests/{family}/{group}/_shared/{unit}",
        f"models/xut_models/{family}/{prim.lower()}.py",
        f"models/xut_models/{family}/_common/{unit}.py",
        f"catalog/{family}/{prim}.overrides.yaml",
    ]


@dataclass(frozen=True)
class TreeState:
    #: ``"sha256:<hex>"`` over the sorted lines ``"<path> <git rev-parse HEAD:<path>>"``
    #: of the paths that exist in HEAD; ``None`` outside a git checkout.
    tree_hash: str | None
    #: ``git rev-parse HEAD``; ``None`` outside a git checkout.
    head: str | None
    #: ``git status --porcelain -- <paths>`` lines (uncommitted or untracked inputs);
    #: ``None`` outside a git checkout.
    dirty: list[str] | None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except (FileNotFoundError, NotADirectoryError):
        return None


def tree_state(root: Path, paths: list[str]) -> TreeState:
    """The git state of ``paths`` under ``root`` (all fields ``None`` if git fails)."""
    root = Path(root)
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    st = _git(root, "status", "--porcelain", "--", *paths)
    if head is None or st is None or head.returncode != 0 or st.returncode != 0:
        return TreeState(None, None, None)
    lines = []
    for p in paths:
        # ``HEAD:./<p>`` is relative to ``root``, which may be below the checkout's top
        r = _git(root, "rev-parse", "--verify", "--quiet", f"HEAD:./{p}")
        if r is not None and r.returncode == 0 and r.stdout.strip():
            lines.append(f"{p} {r.stdout.strip()}")
    text = "".join(f"{line}\n" for line in sorted(lines))
    return TreeState(
        "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        head.stdout.strip(),
        [line.strip() for line in st.stdout.splitlines() if line.strip()],
    )


def case_state(case: TestCase) -> TreeState:
    """``tree_state`` of the primitive ``case`` tests, from its own repository root
    (``<root>/tests/<family>/<group>/<PRIM>``)."""
    root = case.test_dir.parents[3]
    return tree_state(root, tree_paths(case.family, case.group, case.prim, case.work_unit))
