# SPDX-License-Identifier: Apache-2.0
"""Download AMD libraries guides into the local cache (never committed)."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

from xut.errors import FetchError

API = "https://docs.amd.com/api/khub/maps"


@dataclass(frozen=True)
class DocSpec:
    name: str
    edition: str
    map_id: str

    @property
    def pdf_name(self) -> str:
        return f"{self.name}-{self.edition}.pdf"


UG953 = DocSpec("ug953", "2026.1", "i4rliuWFec9CVaGVE8DYrg")


def fetch(
    spec: DocSpec,
    dest_dir: Path,
    session: requests.Session | None = None,
    local: Path | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / spec.pdf_name
    if local is not None:
        shutil.copyfile(local, out)
        return out
    if out.is_file():
        return out
    s = session or requests.Session()
    r = s.get(f"{API}/{spec.map_id}/attachments", timeout=60)
    r.raise_for_status()
    pdfs = [a for a in r.json() if a.get("mimeType") == "application/pdf"]
    if len(pdfs) != 1:
        raise FetchError(f"expected exactly one PDF attachment for {spec}, got {pdfs}")
    r = s.get(f"{API}/{spec.map_id}/attachments/{pdfs[0]['id']}/content", timeout=300)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise FetchError(f"downloaded content for {spec} is not a PDF")
    out.write_bytes(r.content)
    return out


def pdf_to_text(pdf: Path) -> Path:
    txt = pdf.with_suffix(".txt")
    if not txt.is_file():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)
    return txt
