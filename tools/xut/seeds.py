# SPDX-License-Identifier: Apache-2.0
"""The default stimulus seed of a test: the one definition every caller shares.

Dependency-free (standard library only), so both the runners
(``xut.runners.base.seed_for``) and ``xut status record`` can import it."""

import zlib


def default_seed(test_id: str) -> int:
    """``zlib.crc32(test_id)``: stable across runs and hosts, used unless ``--seed`` is
    given."""
    return zlib.crc32(test_id.encode())
