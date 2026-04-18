from __future__ import annotations

import json

from app.db.storage import JobStore
from app.models.job import JobStatus, OCRSettings


def test_store_adds_mirrored_job_and_mapping(tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "folder" / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_root = tmp_path / "output"

    store = JobStore(tmp_path / "data" / "jobs.db")
    store.initialize()

    jobs = store.add_jobs([pdf_path], input_root, output_root, OCRSettings())

    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.QUEUED.value
    assert jobs[0].output_dir == output_root / "folder" / "doc"
    assert jobs[0].log_path and jobs[0].log_path.name == "processing.log"

    mapping = json.loads((output_root / "output_mapping.json").read_text(encoding="utf-8"))
    entry = mapping[jobs[0].id]
    assert entry["original_pdf_path"] == str(pdf_path)
    assert entry["relative_input_path"].replace("\\", "/") == "folder/doc.pdf"
    assert entry["mirrored_output_path"] == str(output_root / "folder" / "doc")
    assert entry["markdown_path"] is None
    assert entry["html_path"] is None
    assert entry["status"] == JobStatus.QUEUED.value


def test_finish_job_updates_required_mapping_fields(tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "folder" / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_root = tmp_path / "output"

    store = JobStore(tmp_path / "data" / "jobs.db")
    store.initialize()
    job = store.add_jobs([pdf_path], input_root, output_root, OCRSettings())[0]
    markdown_path = job.output_dir / "doc.md"
    html_path = job.output_dir / "doc.html"
    metadata_path = job.output_dir / "metadata.json"
    markdown_path.write_text("# Doc", encoding="utf-8")
    html_path.write_text("<h1>Doc</h1>", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    store.finish_job(
        job.id,
        status=JobStatus.COMPLETED,
        markdown_path=markdown_path,
        html_path=html_path,
        metadata_path=metadata_path,
    )

    mapping = json.loads((output_root / "output_mapping.json").read_text(encoding="utf-8"))
    entry = mapping[job.id]
    assert entry["markdown_path"] == str(markdown_path)
    assert entry["html_path"] == str(html_path)
    assert entry["status"] == JobStatus.COMPLETED.value


def test_running_job_is_marked_interrupted(tmp_path):
    input_root = tmp_path / "input"
    pdf_path = input_root / "doc.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    output_root = tmp_path / "output"

    store = JobStore(tmp_path / "data" / "jobs.db")
    store.initialize()
    job = store.add_jobs([pdf_path], input_root, output_root, OCRSettings())[0]

    claimed = store.claim_next_job()
    assert claimed and claimed.id == job.id
    assert store.mark_interrupted_jobs() == 1

    interrupted = store.get_job(job.id)
    assert interrupted.status == JobStatus.INTERRUPTED.value
