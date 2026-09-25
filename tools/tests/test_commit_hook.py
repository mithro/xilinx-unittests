# SPDX-License-Identifier: Apache-2.0
"""Test the commit-msg hook (tools/hooks/commit-msg) via subprocess.

Runs the hook script directly against a temp commit-message file, exactly
as git would invoke it (`<hook> <path-to-commit-msg-file>`), without
installing it as `core.hooksPath` in any worktree.
"""

import subprocess
from pathlib import Path

import pytest
from xut.paths import repo_root

HOOK = repo_root() / "tools/hooks/commit-msg"


def run_hook(tmp_path: Path, subject: str) -> subprocess.CompletedProcess:
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(subject + "\n")
    return subprocess.run(
        [str(HOOK), str(msg_file)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "subject",
    ["flops: add X", "Merge branch x", 'Revert "flops: add X"', "fixup! flops: add X"],
)
def test_accepted_subjects(tmp_path, subject):
    result = run_hook(tmp_path, subject)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("subject", ["Add stuff", "no colon here", ": missing area"])
def test_rejected_subjects(tmp_path, subject):
    result = run_hook(tmp_path, subject)
    assert result.returncode == 1
    assert "commit-msg:" in result.stderr


def test_hook_is_executable():
    assert HOOK.stat().st_mode & 0o111, "tools/hooks/commit-msg must be executable"
