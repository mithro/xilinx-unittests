# SPDX-License-Identifier: Apache-2.0
import pytest

from xut.docs_fetch import UG953, DocSpec, fetch


class FakeResp:
    def __init__(self, *, json_data=None, content=b"", status=200):
        self._j, self.content, self.status_code = json_data, content, status

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, listing, pdf_bytes):
        self.listing, self.pdf, self.calls = listing, pdf_bytes, []

    def get(self, url, timeout):
        self.calls.append(url)
        if url.endswith("/attachments"):
            return FakeResp(json_data=self.listing)
        return FakeResp(content=self.pdf)


def test_fetch_picks_pdf_attachment(tmp_path):
    listing = [
        {"id": "zip1", "filename": "templates.zip", "mimeType": "application/zip"},
        {"id": "pdf1", "filename": "ug953.pdf", "mimeType": "application/pdf"},
    ]
    s = FakeSession(listing, b"%PDF-1.7 fake")
    out = fetch(UG953, tmp_path, session=s)
    assert out.read_bytes().startswith(b"%PDF")
    assert s.calls[-1].endswith("/attachments/pdf1/content")


def test_fetch_is_cached(tmp_path):
    s = FakeSession([{"id": "p", "filename": "a.pdf", "mimeType": "application/pdf"}], b"%PDF-x")
    fetch(UG953, tmp_path, session=s)
    n = len(s.calls)
    fetch(UG953, tmp_path, session=s)
    assert len(s.calls) == n


def test_fetch_rejects_non_pdf(tmp_path):
    s = FakeSession([{"id": "p", "filename": "a.pdf", "mimeType": "application/pdf"}], b"<html>")
    with pytest.raises(ValueError, match="not a PDF"):
        fetch(UG953, tmp_path, session=s)


def test_local_copy_used(tmp_path):
    src = tmp_path / "given.pdf"
    src.write_bytes(b"%PDF-local")
    out = fetch(UG953, tmp_path / "d", local=src)
    assert out.read_bytes() == b"%PDF-local"


def test_docspec_filename():
    assert DocSpec("ug953", "2026.1", "x").pdf_name == "ug953-2026.1.pdf"
