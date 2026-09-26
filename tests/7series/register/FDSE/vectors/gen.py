# SPDX-License-Identifier: Apache-2.0
"""FDSE vector generators (test.yaml: source: vectors/gen.py:<name>).

The recipes live in tests/7series/register/_shared/flops/flop_recipes.py.
"""

import flop_recipes

globals().update(flop_recipes.generators("FDSE"))
