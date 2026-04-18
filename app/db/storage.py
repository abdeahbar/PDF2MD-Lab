from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterable, Iterator
from uuid import uuid4

from app.models.job import JobRecord, JobStatus, OCRSettings, utc_now
from app.services.preview import get_pdf_page_count
from app.utils.paths import build_output_path_plan, resolve_project_path


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._write_lock, self.session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    input_root TEXT,
                    output_root TEXT,
                    relative_pdf_path TEXT,
                    source_pdf TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    status TEXT NOT NULL,
                    page_count INTEGER,
                    processed_pages INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    queued_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT,
                    elapsed_seconds REAL NOT NULL DEFAULT 0,
                    error_text TEXT,
                    log_path TEXT,
                    markdown_path TEXT,
                    html_path TEXT,
                    metadata_path TEXT,
                    settings_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            self._ensure_column(connection, "jobs", "input_root", "TEXT")
            self._ensure_column(connection, "jobs", "output_root", "TEXT")
            self._ensure_column(connection, "jobs", "relative_pdf_path", "TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def mark_interrupted_jobs(self) -> int:
        now = utc_now()
        with self._write_lock, self.session() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = ?",
                (JobStatus.RUNNING.value,),
            ).fetchall()
            job_ids = [str(row["id"]) for row in rows]
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    error_text = COALESCE(error_text, ?)
                WHERE status = ?
                """,
                (
                    JobStatus.INTERRUPTED.value,
                    now,
                    now,
                    "The app stopped while this job was running. Retry it when ready.",
                    JobStatus.RUNNING.value,
                ),
            )
            for job_id in job_ids:
                self._upsert_output_mapping(connection, job_id)
            return int(cursor.rowcount or 0)

    def get_value(self, key: str, default: str | None = None) -> str | None:
        with self.session() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            return str(row["value"])

    def set_value(self, key: str, value: str) -> None:
        with self._write_lock, self.session() as connection:
            connection.execute(
                """
                INSERT INTO settings(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_ocr_settings(self) -> OCRSettings:
        raw = self.get_value("ocr_settings")
        return OCRSettings.from_json(raw)

    def save_ocr_settings(self, settings: OCRSettings) -> None:
        self.set_value("ocr_settings", settings.normalized().to_json())

    def add_jobs(
        self,
        pdf_paths: Iterable[Path],
        input_root: Path,
        output_root: Path,
        settings: OCRSettings,
    ) -> list[JobRecord]:
        input_root = resolve_project_path(input_root)
        output_root = resolve_project_path(output_root)
        normalized_settings = settings.normalized()
        now = utc_now()
        created: list[JobRecord] = []

        with self._write_lock, self.session() as connection:
            for pdf_path in pdf_paths:
                source_pdf = Path(pdf_path).expanduser().resolve()
                if not source_pdf.exists():
                    raise FileNotFoundError(f"PDF not found: {source_pdf}")

                path_plan = build_output_path_plan(output_root, input_root, source_pdf)
                output_dir = path_plan.output_dir
                output_dir.mkdir(parents=True, exist_ok=False)
                log_path = output_dir / "processing.log"
                log_path.write_text(f"Queued {source_pdf}\n", encoding="utf-8")

                job_id = str(uuid4())
                page_count = get_pdf_page_count(source_pdf)
                connection.execute(
                    """
                    INSERT INTO jobs(
                        id, input_root, output_root, relative_pdf_path, source_pdf, output_dir,
                        status, page_count, processed_pages,
                        created_at, queued_at, updated_at, elapsed_seconds, error_text,
                        log_path, settings_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        job_id,
                        str(input_root),
                        str(output_root),
                        str(path_plan.relative_pdf_path),
                        str(source_pdf),
                        str(output_dir),
                        JobStatus.QUEUED.value,
                        page_count,
                        now,
                        now,
                        now,
                        str(log_path),
                        normalized_settings.to_json(),
                    ),
                )
                self._upsert_output_mapping(connection, job_id)
                created.append(self.get_job(job_id, connection=connection))
        return created

    def list_jobs(self, status: str | None = None, limit: int = 500) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: tuple[object, ...] = ()
        if status and status != "all":
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY created_at DESC LIMIT ?"
        params = (*params, limit)
        with self.session() as connection:
            return [self._row_to_job(row) for row in connection.execute(query, params).fetchall()]

    def get_job(self, job_id: str, connection: sqlite3.Connection | None = None) -> JobRecord:
        own_connection = connection is None
        if connection is None:
            connection = self.connect()
        try:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Job not found: {job_id}")
            return self._row_to_job(row)
        finally:
            if own_connection:
                connection.close()

    def get_running_jobs(self) -> list[JobRecord]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY started_at ASC",
                (JobStatus.RUNNING.value,),
            ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        with self.session() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
        counts = {status.value: 0 for status in JobStatus}
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        counts["total"] = sum(counts.values())
        return counts

    def claim_next_job(self) -> JobRecord | None:
        now = utc_now()
        with self._write_lock, self.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id
                FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if not row:
                connection.execute("COMMIT")
                return None

            job_id = str(row["id"])
            connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    error_text = NULL,
                    processed_pages = 0
                WHERE id = ?
                """,
                (JobStatus.RUNNING.value, now, now, job_id),
            )
            connection.execute("COMMIT")
            self._upsert_output_mapping(connection, job_id)
            return self.get_job(job_id, connection=connection)

    def update_progress(
        self,
        job_id: str,
        *,
        page_count: int | None = None,
        processed_pages: int | None = None,
    ) -> None:
        now = utc_now()
        assignments = ["updated_at = ?", "elapsed_seconds = ?"]
        params: list[object] = [now, self._elapsed_seconds_for_job(job_id, now)]
        if page_count is not None:
            assignments.append("page_count = ?")
            params.append(page_count)
        if processed_pages is not None:
            assignments.append("processed_pages = ?")
            params.append(max(0, processed_pages))
        params.append(job_id)

        with self._write_lock, self.session() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                tuple(params),
            )

    def finish_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error_text: str | None = None,
        markdown_path: Path | None = None,
        html_path: Path | None = None,
        metadata_path: Path | None = None,
        page_count: int | None = None,
        processed_pages: int | None = None,
    ) -> None:
        now = utc_now()
        elapsed = self._elapsed_seconds_for_job(job_id, now)
        with self._write_lock, self.session() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    finished_at = ?,
                    updated_at = ?,
                    elapsed_seconds = ?,
                    error_text = ?,
                    markdown_path = COALESCE(?, markdown_path),
                    html_path = COALESCE(?, html_path),
                    metadata_path = COALESCE(?, metadata_path),
                    page_count = COALESCE(?, page_count),
                    processed_pages = COALESCE(?, processed_pages)
                WHERE id = ?
                """,
                (
                    status.value,
                    now,
                    now,
                    elapsed,
                    error_text,
                    str(markdown_path) if markdown_path else None,
                    str(html_path) if html_path else None,
                    str(metadata_path) if metadata_path else None,
                    page_count,
                    processed_pages,
                    job_id,
                ),
            )
            self._upsert_output_mapping(connection, job_id)

    def retry_failed_jobs(self) -> int:
        now = utc_now()
        retry_statuses = (
            JobStatus.FAILED.value,
            JobStatus.INTERRUPTED.value,
            JobStatus.CANCELLED.value,
        )
        with self._write_lock, self.session() as connection:
            rows = connection.execute(
                f"SELECT id FROM jobs WHERE status IN ({','.join('?' for _ in retry_statuses)})",
                retry_statuses,
            ).fetchall()
            job_ids = [str(row["id"]) for row in rows]
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET status = ?,
                    queued_at = ?,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?,
                    processed_pages = 0,
                    elapsed_seconds = 0,
                    error_text = NULL
                WHERE status IN ({','.join('?' for _ in retry_statuses)})
                """,
                (JobStatus.QUEUED.value, now, now, *retry_statuses),
            )
            for job_id in job_ids:
                self._upsert_output_mapping(connection, job_id)
            return int(cursor.rowcount or 0)

    def _ensure_column(self, connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def _upsert_output_mapping(self, connection: sqlite3.Connection, job_id: str) -> None:
        job = self.get_job(job_id, connection=connection)
        if not job.output_root:
            return

        mapping_path = job.output_root / "output_mapping.json"
        try:
            existing = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
        except json.JSONDecodeError:
            existing = {}

        existing[job.id] = {
            "original_pdf_path": str(job.source_pdf),
            "relative_input_path": str(job.relative_pdf_path or job.source_pdf.name),
            "mirrored_output_path": str(job.output_dir),
            "markdown_path": str(job.markdown_path) if job.markdown_path else None,
            "html_path": str(job.html_path) if job.html_path else None,
            "metadata_path": str(job.metadata_path) if job.metadata_path else None,
            "log_path": str(job.log_path) if job.log_path else None,
            "status": job.status,
        }
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = mapping_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(mapping_path)

    def _elapsed_seconds_for_job(self, job_id: str, end_time: str) -> float:
        with self.session() as connection:
            row = connection.execute("SELECT started_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row or not row["started_at"]:
            return 0.0
        try:
            started = datetime.fromisoformat(str(row["started_at"]))
            ended = datetime.fromisoformat(end_time)
        except ValueError:
            return 0.0
        return max(0.0, (ended - started).total_seconds())

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=str(row["id"]),
            source_pdf=Path(str(row["source_pdf"])),
            output_dir=Path(str(row["output_dir"])),
            status=str(row["status"]),
            input_root=Path(str(row["input_root"])) if "input_root" in row.keys() and row["input_root"] else None,
            output_root=Path(str(row["output_root"])) if "output_root" in row.keys() and row["output_root"] else None,
            relative_pdf_path=Path(str(row["relative_pdf_path"])) if "relative_pdf_path" in row.keys() and row["relative_pdf_path"] else None,
            page_count=row["page_count"],
            processed_pages=int(row["processed_pages"] or 0),
            created_at=str(row["created_at"]),
            queued_at=row["queued_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=row["updated_at"],
            elapsed_seconds=float(row["elapsed_seconds"] or 0),
            error_text=row["error_text"],
            log_path=Path(str(row["log_path"])) if row["log_path"] else None,
            markdown_path=Path(str(row["markdown_path"])) if row["markdown_path"] else None,
            html_path=Path(str(row["html_path"])) if row["html_path"] else None,
            metadata_path=Path(str(row["metadata_path"])) if row["metadata_path"] else None,
            settings=OCRSettings.from_json(row["settings_json"]),
        )
