from __future__ import annotations

import logging
from pathlib import Path
import threading
import time

from app.db.storage import JobStore
from app.models.job import JobStatus
from app.services.ocr_provider import provider_for


LOGGER = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self._stop_event = threading.Event()
        self._paused = False
        self._lock = threading.RLock()
        self._workers: list[threading.Thread] = []
        self._active_cancel_events: dict[str, threading.Event] = {}

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def start(self, max_workers: int = 1) -> None:
        max_workers = max(1, min(int(max_workers or 1), 2))
        with self._lock:
            self._paused = False
            self._stop_event.clear()
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            missing = max_workers - len(self._workers)
            for index in range(missing):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"chandra-ocr-worker-{len(self._workers) + index + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def cancel_current(self) -> int:
        with self._lock:
            events = list(self._active_cancel_events.values())
        for event in events:
            event.set()
        return len(events)

    def active_job_ids(self) -> list[str]:
        with self._lock:
            return list(self._active_cancel_events.keys())

    def worker_count(self) -> int:
        with self._lock:
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            return len(self._workers)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.paused:
                time.sleep(0.5)
                continue

            job = self.store.claim_next_job()
            if job is None:
                time.sleep(1.0)
                continue

            cancel_event = threading.Event()
            with self._lock:
                self._active_cancel_events[job.id] = cancel_event

            try:
                LOGGER.info("Starting OCR job %s for %s", job.id, job.source_pdf)
                provider = provider_for(job.settings)
                result = provider.run(
                    job,
                    job.settings,
                    cancel_event,
                    lambda page_count, processed_pages, job_id=job.id: self.store.update_progress(
                        job_id,
                        page_count=page_count,
                        processed_pages=processed_pages,
                    ),
                )
                self.store.finish_job(
                    job.id,
                    status=result.status,
                    error_text=result.error_text,
                    markdown_path=result.markdown_path,
                    html_path=result.html_path,
                    metadata_path=result.metadata_path,
                    page_count=result.page_count,
                    processed_pages=result.processed_pages,
                )
                LOGGER.info("Finished OCR job %s with status %s", job.id, result.status.value)
            except Exception as exc:
                LOGGER.exception("OCR job failed: %s", job.id)
                self._append_log(job.log_path, f"\nJob failed: {exc}\n")
                self.store.finish_job(
                    job.id,
                    status=JobStatus.CANCELLED if cancel_event.is_set() else JobStatus.FAILED,
                    error_text=str(exc),
                )
            finally:
                with self._lock:
                    self._active_cancel_events.pop(job.id, None)

    @staticmethod
    def _append_log(log_path: Path | None, text: str) -> None:
        if not log_path:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)

