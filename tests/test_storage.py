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
    assert mapping[jobs[0].id]["relative_input_path"].replace("\\", "/") == "folder/doc.pdf"


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
