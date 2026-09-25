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


@main.group("catalog")
def catalog_grp() -> None:
    """Primitive catalog (catalog/<family>/<PRIM>.yaml)."""


EXPECTED_PRIMITIVES = 103


@catalog_grp.command("build")
def catalog_build_cmd() -> None:
    """Regenerate catalog/7series/*.yaml and catalog/EXTRACTION_REPORT.md."""
    from xut.catalog.build import FAMILY, build_all, render_report
    from xut.catalog.ug953 import names_from_text
    from xut.docs_fetch import UG953, fetch, pdf_to_text
    from xut.paths import VIVADO_RETARGET, VIVADO_UNISIM, cache_dir, repo_root, submodule_unisim

    text = pdf_to_text(fetch(UG953, cache_dir() / "docs"))
    names = names_from_text(text.read_text())
    if len(names) != EXPECTED_PRIMITIVES:
        raise click.ClickException(
            f"expected {EXPECTED_PRIMITIVES} UG953 primitive sections, found {len(names)}"
        )
    if VIVADO_UNISIM.is_dir():
        search = [VIVADO_UNISIM, VIVADO_RETARGET]
    else:
        search = [submodule_unisim()]
        click.echo(f"warning: {VIVADO_UNISIM} not found, using {search[0]}", err=True)
    root = repo_root()
    out = root / "catalog" / FAMILY
    report = build_all(text, names, out, search)
    sources = "the UNISIM models in " + ", ".join(f"`{s.name}/`" for s in search)
    (root / "catalog" / "EXTRACTION_REPORT.md").write_text(render_report(report, names, sources))
    only_in = sum(" only in " in line for line in report)
    click.echo(
        f"wrote {len(names)} entries to {out}; {len(report)} report lines ({only_in} only-in)"
    )
