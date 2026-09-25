# SPDX-License-Identifier: Apache-2.0
"""Command-line entry point."""

from pathlib import Path

import click

from xut import __version__


@click.group()
@click.version_option(__version__, prog_name="xut")
def main() -> None:
    """Xilinx primitive test-suite tooling."""


@main.command("fetch-docs")
@click.option("--local", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def fetch_docs_cmd(local: Path | None) -> None:
    """Download UG953 into .cache/docs (or copy a local PDF there)."""
    from xut.docs_fetch import UG953, fetch, pdf_to_text
    from xut.paths import cache_dir

    pdf = fetch(UG953, cache_dir() / "docs", local=local)
    click.echo(f"pdf:  {pdf}\ntext: {pdf_to_text(pdf)}")
