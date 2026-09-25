# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point."""

import click

from xut import __version__


@click.group()
@click.version_option(__version__, prog_name="xut")
def main() -> None:
    """Xilinx primitive test-suite tooling."""
