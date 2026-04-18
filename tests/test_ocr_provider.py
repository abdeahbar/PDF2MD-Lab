from __future__ import annotations

from app.services.ocr_provider import ChandraHFProvider


def test_normalize_output_files_creates_required_layout(tmp_path):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "file.md").write_text("![scan](page_1.png)\n", encoding="utf-8")
    (output_dir / "file.html").write_text('<img src="page_1.png">', encoding="utf-8")
    (output_dir / "file_metadata.json").write_text('{"num_pages": 1}', encoding="utf-8")
    (output_dir / "page_1.png").write_bytes(b"png")

    markdown_path, html_path, metadata_path = ChandraHFProvider()._normalize_output_files(output_dir, "file")

    assert markdown_path == output_dir / "file.md"
    assert html_path == output_dir / "file.html"
    assert metadata_path == output_dir / "metadata.json"
    assert not (output_dir / "file_metadata.json").exists()
    assert (output_dir / "images" / "page_1.png").exists()
    assert "images/page_1.png" in markdown_path.read_text(encoding="utf-8")
    assert "images/page_1.png" in html_path.read_text(encoding="utf-8")

