from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any


DEFAULT_MODEL_REPO = "datalab-to/chandra-ocr-2"
DEFAULT_LOCAL_MODEL_PATH = "models/chandra-ocr-2"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.INTERRUPTED.value,
}


@dataclass(slots=True)
class OCRSettings:
    method: str = "hf"
    batch_size: int = 1
    max_parallel_jobs: int = 1
    safe_mode: bool = True
    include_images: bool = True
    include_headers_footers: bool = False
    page_range: str | None = None
    max_output_tokens: int | None = 12384
    offline_mode: bool = True
    model_checkpoint: str = DEFAULT_MODEL_REPO
    local_model_path: str = DEFAULT_LOCAL_MODEL_PATH

    def normalized(self) -> "OCRSettings":
        batch_size = max(1, min(int(self.batch_size or 1), 4))
        max_parallel_jobs = 1 if self.safe_mode else max(1, min(int(self.max_parallel_jobs or 1), 2))
        page_range = (self.page_range or "").strip() or None
        max_output_tokens = self.max_output_tokens if self.max_output_tokens and self.max_output_tokens > 0 else None
        method = (self.method or "hf").lower().strip()
        if method != "hf":
            method = "hf"
        return OCRSettings(
            method=method,
            batch_size=batch_size,
            max_parallel_jobs=max_parallel_jobs,
            safe_mode=bool(self.safe_mode),
            include_images=bool(self.include_images),
            include_headers_footers=bool(self.include_headers_footers),
            page_range=page_range,
            max_output_tokens=max_output_tokens,
            offline_mode=bool(self.offline_mode),
            model_checkpoint=(self.model_checkpoint or DEFAULT_MODEL_REPO).strip(),
            local_model_path=(self.local_model_path or DEFAULT_LOCAL_MODEL_PATH).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "method": normalized.method,
            "batch_size": normalized.batch_size,
            "max_parallel_jobs": normalized.max_parallel_jobs,
            "safe_mode": normalized.safe_mode,
            "include_images": normalized.include_images,
            "include_headers_footers": normalized.include_headers_footers,
            "page_range": normalized.page_range,
            "max_output_tokens": normalized.max_output_tokens,
            "offline_mode": normalized.offline_mode,
            "model_checkpoint": normalized.model_checkpoint,
            "local_model_path": normalized.local_model_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OCRSettings":
        if not data:
            return cls()
        return cls(
            method=str(data.get("method") or "hf"),
            batch_size=int(data.get("batch_size") or 1),
            max_parallel_jobs=int(data.get("max_parallel_jobs") or 1),
            safe_mode=bool(data.get("safe_mode", True)),
            include_images=bool(data.get("include_images", True)),
            include_headers_footers=bool(data.get("include_headers_footers", False)),
            page_range=data.get("page_range") or None,
            max_output_tokens=data.get("max_output_tokens"),
            offline_mode=bool(data.get("offline_mode", True)),
            model_checkpoint=str(data.get("model_checkpoint") or DEFAULT_MODEL_REPO),
            local_model_path=str(data.get("local_model_path") or DEFAULT_LOCAL_MODEL_PATH),
        ).normalized()

    @classmethod
    def from_json(cls, raw: str | None) -> "OCRSettings":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls()
        return cls.from_dict(data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass(slots=True)
class JobRecord:
    id: str
    source_pdf: Path
    output_dir: Path
    status: str
    created_at: str
    input_root: Path | None = None
    output_root: Path | None = None
    relative_pdf_path: Path | None = None
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    page_count: int | None = None
    processed_pages: int = 0
    elapsed_seconds: float = 0.0
    error_text: str | None = None
    log_path: Path | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    metadata_path: Path | None = None
    settings: OCRSettings = field(default_factory=OCRSettings)

    @property
    def filename(self) -> str:
        return self.source_pdf.name

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def progress_fraction(self) -> float:
        if not self.page_count:
            return 0.0
        return max(0.0, min(1.0, self.processed_pages / self.page_count))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
