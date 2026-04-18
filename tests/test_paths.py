from __future__ import annotations

from app.utils.paths import build_output_path_plan


def test_output_path_mirrors_nested_unicode_input(tmp_path):
    input_root = tmp_path / "PDF_INPUT"
    lycee = "Lyc\u00e9e"
    grade = "1\u00e8re Bac"
    pdf_path = input_root / "Maroc" / lycee / grade / "Anglais" / "Test 1" / "file.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    output_root = tmp_path / "OCR_OUTPUT"
    plan = build_output_path_plan(output_root, input_root, pdf_path)

    assert plan.relative_pdf_path.as_posix() == f"Maroc/{lycee}/{grade}/Anglais/Test 1/file.pdf"
    assert plan.output_dir == output_root / "Maroc" / lycee / grade / "Anglais" / "Test 1" / "file"


def test_output_path_versions_existing_folder(tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "nested" / "file.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")

    output_root = tmp_path / "out"
    existing = output_root / "nested" / "file"
    existing.mkdir(parents=True)

    plan = build_output_path_plan(output_root, input_root, pdf_path)

    assert plan.output_dir == output_root / "nested" / "file_v2"
