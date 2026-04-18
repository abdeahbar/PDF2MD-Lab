from __future__ import annotations

from app.services import discovery


def test_discovery_skips_page_counts_by_default(monkeypatch, tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "nested" / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fail_page_count(*_args: object) -> int:
        raise AssertionError("page count should not be read during the fast scan")

    monkeypatch.setattr(discovery, "get_pdf_page_count", fail_page_count)

    found = discovery.discover_pdfs(input_root)

    assert len(found) == 1
    assert found[0].path == pdf_path.resolve()
    assert found[0].page_count is None


def test_discovery_can_include_page_counts(monkeypatch, tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(discovery, "get_pdf_page_count", lambda _path: 7)

    found = discovery.discover_pdfs(input_root, include_page_counts=True)

    assert found[0].page_count == 7
