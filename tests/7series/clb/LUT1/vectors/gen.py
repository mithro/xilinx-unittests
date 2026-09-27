# SPDX-License-Identifier: Apache-2.0
"""LUT1 vector generators (test.yaml: source: vectors/gen.py:<name>).

The recipes live in tests/7series/clb/_shared/luts/luts_recipes.py.
"""

import luts_recipes

globals().update(luts_recipes.generators("LUT1"))
