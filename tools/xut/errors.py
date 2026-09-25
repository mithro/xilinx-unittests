# SPDX-License-Identifier: Apache-2.0
"""User-facing error types.

Every failure a user can cause (running outside the checkout, a bad
`docs/work-units.yaml`, a schema-invalid status file, a missing git ref, ...) is raised
as a `XutError`. The CLI's root group turns any `XutError` into a clean `Error: ...`
line and exit code 1; anything else is a bug and keeps its traceback.

Each concrete type also subclasses the builtin it replaces, so callers that catch the
builtin (and tests written against it) keep working.
"""


class XutError(Exception):
    """A user-facing failure; its message is shown without a traceback."""

    def __str__(self) -> str:
        # KeyError.__str__ reprs its argument; show every XutError's message verbatim.
        return str(self.args[0]) if len(self.args) == 1 else super().__str__()


class NotInRepoError(XutError, FileNotFoundError):
    """The current directory is not inside a xilinx-unittests checkout."""


class ConfigError(XutError, ValueError):
    """A repository input (work-units map, status file, test.yaml, ...) is invalid."""


class OverrideError(XutError, KeyError):
    """A `<PRIM>.overrides.yaml` names a port/attribute the entry doesn't have."""


class OverrideTypeError(XutError, TypeError):
    """A `<PRIM>.overrides.yaml` section has the wrong shape."""


class GitError(XutError, RuntimeError):
    """A git command failed or a ref could not be resolved."""


class FetchError(XutError, ValueError):
    """A documentation download did not produce the expected PDF."""
