from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from typing import Callable

from app.models.job import JobRecord, JobStatus, OCRSettings
from app.services.model_cache import check_model_availability
from app.utils.paths import resolve_project_path


ProgressCallback = Callable[[int | None, int | None], None]

LOADED_RE = re.compile(r"Loaded\s+(\d+)\s+page", re.IGNORECASE)
PROCESSING_RE = re.compile(r"Processing pages\s+(\d+)-(\d+)", re.IGNORECASE)
SAVED_RE = re.compile(r"Saved:.*\((\d+)\s+page", re.IGNORECASE)
ERROR_RE = re.compile(r"Error processing .*?:\s*(.*)", re.IGNORECASE)


@dataclass(slots=True)
class OCRRunResult:
    status: JobStatus
    error_text: str | None = None
    markdown_path: Path | None = None
    html_path: Path | None = None
    metadata_path: Path | None = None
    page_count: int | None = None
    processed_pages: int | None = None


class OCRProvider(ABC):
    name: str

    @abstractmethod
    def run(
        self,
        job: JobRecord,
        settings: OCRSettings,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> OCRRunResult:
        raise NotImplementedError


class ChandraHFProvider(OCRProvider):
    name = "hf"

    def run(
        self,
        job: JobRecord,
        settings: OCRSettings,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> OCRRunResult:
        settings = settings.normalized()
        self._validate_runtime(settings)

        job.output_dir.mkdir(parents=True, exist_ok=True)
        temp_parent = job.output_dir / ".chandra_tmp"
        if temp_parent.exists():
            shutil.rmtree(temp_parent)
        temp_parent.mkdir(parents=True, exist_ok=True)

        log_path = job.log_path or (job.output_dir / "processing.log")
        command = self._build_command(job.source_pdf, temp_parent, settings)
        env = self._build_environment(settings)
        page_count = job.page_count
        processed_pages = job.processed_pages
        last_error: str | None = None

        self._append_log(log_path, "\nStarting Chandra OCR\n")
        self._append_log(log_path, f"Command: {' '.join(command)}\n")
        self._append_log(log_path, f"Output folder: {job.output_dir}\n")

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform.startswith("win") else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )

        assert process.stdout is not None
        try:
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                self._append_log(log_path, line + "\n")

                loaded = LOADED_RE.search(line)
                if loaded:
                    page_count = int(loaded.group(1))
                    progress_callback(page_count, processed_pages)

                processing = PROCESSING_RE.search(line)
                if processing:
                    processed_pages = max(0, int(processing.group(1)) - 1)
                    progress_callback(page_count, processed_pages)

                saved = SAVED_RE.search(line)
                if saved:
                    processed_pages = int(saved.group(1))
                    page_count = page_count or processed_pages
                    progress_callback(page_count, processed_pages)

                error = ERROR_RE.search(line)
                if error:
                    last_error = error.group(1).strip() or line

                if cancel_event.is_set():
                    self._terminate(process)
                    self._append_log(log_path, "Cancellation requested. Chandra process stopped.\n")
                    return OCRRunResult(
                        status=JobStatus.CANCELLED,
                        error_text="Cancelled by user.",
                        page_count=page_count,
                        processed_pages=processed_pages,
                    )

            return_code = process.wait()
        finally:
            if process.poll() is None:
                self._terminate(process)

        markdown_path, html_path, metadata_path = self._collect_outputs(job, temp_parent)
        metadata_page_count = self._read_metadata_page_count(metadata_path)
        if metadata_page_count:
            page_count = metadata_page_count
            processed_pages = metadata_page_count

        if return_code != 0:
            return OCRRunResult(
                status=JobStatus.FAILED,
                error_text=last_error or f"Chandra exited with code {return_code}. See processing.log for details.",
                markdown_path=markdown_path,
                html_path=html_path,
                metadata_path=metadata_path,
                page_count=page_count,
                processed_pages=processed_pages,
            )

        if not markdown_path or not markdown_path.exists():
            return OCRRunResult(
                status=JobStatus.FAILED,
                error_text=last_error or "Chandra finished but no markdown output was produced. See processing.log for details.",
                html_path=html_path,
                metadata_path=metadata_path,
                page_count=page_count,
                processed_pages=processed_pages,
            )

        self._append_log(log_path, "Finished successfully.\n")
        return OCRRunResult(
            status=JobStatus.COMPLETED,
            markdown_path=markdown_path,
            html_path=html_path,
            metadata_path=metadata_path,
            page_count=page_count,
            processed_pages=processed_pages or page_count,
        )

    def _validate_runtime(self, settings: OCRSettings) -> None:
        if importlib.util.find_spec("chandra") is None:
            raise RuntimeError("Chandra OCR is not installed. Run pip install -r requirements.txt.")

        if settings.offline_mode:
            availability = check_model_availability(settings.local_model_path, settings.model_checkpoint)
            if not availability.available:
                raise RuntimeError("Model is not downloaded yet. Connect to internet once and run setup.")

    def _build_command(self, source_pdf: Path, output_parent: Path, settings: OCRSettings) -> list[str]:
        chandra_exe = shutil.which("chandra")
        if chandra_exe:
            command = [chandra_exe]
        else:
            command = [sys.executable, "-m", "chandra.scripts.cli"]

        command.extend([str(source_pdf), str(output_parent), "--method", "hf"])
        command.extend(["--batch-size", str(settings.batch_size)])
        command.append("--include-images" if settings.include_images else "--no-images")
        command.append("--include-headers-footers" if settings.include_headers_footers else "--no-headers-footers")
        command.append("--save-html")

        if settings.page_range:
            command.extend(["--page-range", settings.page_range])
        if settings.max_output_tokens:
            command.extend(["--max-output-tokens", str(settings.max_output_tokens)])
        return command

    def _build_environment(self, settings: OCRSettings) -> dict[str, str]:
        env = os.environ.copy()
        local_model_path = resolve_project_path(settings.local_model_path)
        if local_model_path.exists():
            env["MODEL_CHECKPOINT"] = str(local_model_path)
        else:
            env["MODEL_CHECKPOINT"] = settings.model_checkpoint

        if settings.max_output_tokens:
            env["MAX_OUTPUT_TOKENS"] = str(settings.max_output_tokens)

        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        if settings.offline_mode:
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            env["HF_DATASETS_OFFLINE"] = "1"
        return env

    def _collect_outputs(self, job: JobRecord, temp_parent: Path) -> tuple[Path | None, Path | None, Path | None]:
        source_output = temp_parent / job.source_pdf.stem
        if not source_output.exists():
            children = [path for path in temp_parent.iterdir() if path.is_dir()]
            source_output = children[0] if children else temp_parent

        if source_output.exists():
            for item in source_output.iterdir():
                destination = job.output_dir / item.name
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.move(str(item), str(destination))

        if temp_parent.exists():
            shutil.rmtree(temp_parent, ignore_errors=True)

        markdown_path, html_path, metadata_path = self._normalize_output_files(job.output_dir, job.source_pdf.stem)
        return markdown_path, html_path, metadata_path

    @staticmethod
    def _first_existing(paths: object, *, exclude_dirs: bool = True) -> Path | None:
        for path in paths:  # type: ignore[assignment]
            candidate = Path(path)
            if candidate.exists() and not (exclude_dirs and candidate.is_dir()):
                return candidate
        return None

    def _normalize_output_files(self, output_dir: Path, source_stem: str) -> tuple[Path | None, Path | None, Path | None]:
        markdown_path = self._first_existing([output_dir / f"{source_stem}.md"]) or self._first_existing(output_dir.glob("*.md"))
        html_path = self._first_existing([output_dir / f"{source_stem}.html"]) or self._first_existing(output_dir.glob("*.html"))
        metadata_path = self._normalize_metadata(output_dir, source_stem)
        moved_images = self._move_images_to_folder(output_dir)
        self._rewrite_image_references([markdown_path, html_path], moved_images)
        return markdown_path, html_path, metadata_path

    def _normalize_metadata(self, output_dir: Path, source_stem: str) -> Path | None:
        target = output_dir / "metadata.json"
        candidates = [
            output_dir / f"{source_stem}_metadata.json",
            *sorted(output_dir.glob("*_metadata.json")),
        ]
        source = self._first_existing(candidates)
        if not source:
            return target if target.exists() else None
        source.replace(target)
        return target

    @staticmethod
    def _read_metadata_page_count(metadata_path: Path | None) -> int | None:
        if not metadata_path or not metadata_path.exists():
            return None
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        page_count = data.get("num_pages")
        return int(page_count) if page_count else None

    @staticmethod
    def _move_images_to_folder(output_dir: Path) -> dict[str, str]:
        image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
        images_dir = output_dir / "images"
        moved: dict[str, str] = {}
        for image_path in output_dir.iterdir():
            if image_path.is_file() and image_path.suffix.lower() in image_suffixes:
                images_dir.mkdir(exist_ok=True)
                destination = images_dir / image_path.name
                if destination.exists():
                    destination.unlink()
                image_path.replace(destination)
                moved[image_path.name] = f"images/{image_path.name}"
        return moved

    @staticmethod
    def _rewrite_image_references(paths: list[Path | None], moved_images: dict[str, str]) -> None:
        if not moved_images:
            return
        for path in paths:
            if not path or not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            updated = text
            for filename, relative_path in moved_images.items():
                updated = re.sub(rf'(?<!images/){re.escape(filename)}', relative_path, updated)
            if updated != text:
                path.write_text(updated, encoding="utf-8")

    @staticmethod
    def _append_log(log_path: Path, text: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)


class ChandraVLLMProvider(OCRProvider):
    name = "vllm"

    def run(
        self,
        job: JobRecord,
        settings: OCRSettings,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> OCRRunResult:
        return OCRRunResult(
            status=JobStatus.FAILED,
            error_text="The vLLM provider is reserved for a future optional mode and is not enabled in this MVP.",
        )


def provider_for(settings: OCRSettings) -> OCRProvider:
    if settings.normalized().method == "hf":
        return ChandraHFProvider()
    return ChandraVLLMProvider()
