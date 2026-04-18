# AGENTS.md

Guidance for Codex and other coding agents working on **Chandra OCR Batch PDF to Markdown UI**.

## 1. Project Overview

This project is a simple local-first Windows application for processing many PDF files with Chandra OCR and converting the results into Markdown and HTML. The app provides a Streamlit UI for scanning input folders, selecting PDFs, queueing work, tracking progress, reviewing per-document status, and previewing the transformed output beside the original PDF.

The primary goal is an MVP that runs privately on the user's machine. After initial dependency installation and model download, document processing must work offline with no cloud calls, no external APIs, and no file uploads.

Preferred stack:

- Python 3.11
- Streamlit UI
- SQLite job persistence
- Local filesystem storage
- Chandra OCR through the Hugging Face backend by default
- Optional future vLLM provider stub only; vLLM must not be required for the MVP
- PyMuPDF or pypdfium2 for PDF preview and rendering
- `pathlib` for file handling
- Standard Python logging
- No Docker for the MVP
- No Redis
- No Celery
- No authentication

Expected project structure:

```text
app/
  ui/
  core/
  services/
  db/
  models/
  utils/
data/
  jobs.db
outputs/
models/
  chandra-ocr-2/
tests/
README.md
requirements.txt
AGENTS.md
```

## 2. Non-Negotiable Rules

- The app is local-first. PDFs, generated files, logs, metadata, database records, and model files stay on the local machine.
- The app must work offline after first setup.
- Internet access is allowed only for initial dependency installation and model download.
- In offline mode, make no cloud calls, no external API calls, and no network requests for model files.
- Never upload PDFs, output files, metadata, logs, or previews anywhere.
- Do not flatten output folders.
- Preserve the input folder structure under the selected output root.
- Use paths relative to the selected input root when generating mirrored outputs.
- Keep processing concurrency conservative. Sequential processing is the default.
- Keep the MVP simple. Do not introduce distributed queues, background services, web accounts, multi-user features, or deployment machinery unless explicitly requested.
- Prefer clear, boring code over clever abstractions.

## 3. Architecture Guidelines

Use a small layered architecture with explicit boundaries.

### Streamlit UI Layer

The UI belongs under `app/ui/` and should handle:

- Input folder selection
- Output folder selection
- Recursive PDF scan results
- PDF selection controls
- Queue controls
- Batch progress
- Per-document status table
- Status filtering
- Document detail and preview panes
- Retry controls for failed documents
- Offline mode controls and model availability display

The UI should call service/core APIs. It should not directly implement OCR, output path mirroring, SQLite persistence, or queue state transitions.

### OCR Provider Abstraction

Define a small OCR provider interface in the core or services layer. The interface should hide backend-specific details from the job runner.

Suggested behavior:

- `is_available() -> bool`
- `ensure_available(offline: bool) -> None`
- `process_pdf(pdf_path: Path, output_dir: Path, options: OcrOptions) -> OcrResult`
- Backend-specific model loading should stay inside provider implementations.

### ChandraHFProvider

`ChandraHFProvider` is the default OCR backend. It should:

- Use local model files when offline mode is enabled.
- Set `HF_HUB_OFFLINE=1` when offline mode is enabled.
- Pass `local_files_only=True` to Hugging Face/model-loading APIs when supported.
- Load model files from the local project model path by default, such as `models/chandra-ocr-2/`.
- Show or raise a clear error when model files are missing:

```text
Model is not downloaded yet. Connect to internet once and run setup.
```

### ChandraVLLMProvider Stub

An optional future `ChandraVLLMProvider` may exist as a stub, but it must not be required for the MVP. Do not require vLLM dependencies in the default install path unless the user explicitly asks for vLLM support.

### SQLite Job Store

Use SQLite for persistent job and document state. The database should live under `data/jobs.db` by default.

The database layer belongs under `app/db/` and should provide focused functions/classes for:

- Creating jobs
- Adding scanned/selected documents
- Updating document status
- Recording processing events/logs
- Reading settings
- Writing settings
- Resuming or marking interrupted work after app restart

### Filesystem Output Manager

Create a filesystem output manager under `app/services/` or `app/core/`. It is responsible for:

- Mirroring input folder structure under the output root
- Creating one output directory per source PDF
- Writing Markdown, HTML, metadata JSON, extracted images, and processing logs
- Handling Windows path length risks
- Producing `output_mapping.json` when shortened paths are necessary
- Avoiding silent overwrites

### Preview Service

Create a preview service for:

- Rendering or extracting PDF page previews using PyMuPDF or pypdfium2
- Loading generated Markdown
- Loading generated HTML
- Providing safe local-only preview data to the Streamlit UI

The preview service must read only local files.

### Queue and Job Runner

The queue/job runner should:

- Process selected PDFs one by one by default
- Persist status transitions in SQLite
- Catch per-document failures
- Continue the batch after a document fails
- Write per-document logs and error text
- Release resources between documents where possible
- Mark interrupted jobs/documents after restart

Keep the queue simple for the MVP. An in-process runner is acceptable. Do not introduce Celery, Redis, or a separate worker service.

## 4. Coding Style

- Use Python 3.11.
- Use type hints for public functions, service interfaces, data models, and non-trivial helpers.
- Use `pathlib.Path` for file handling. Avoid raw string path hacks and manual slash manipulation.
- Keep modules small and focused.
- Prefer readable functions with clear inputs and outputs.
- Use clear error handling. Convert backend exceptions into readable application errors at service boundaries.
- Use standard Python `logging`.
- Include structured context in log messages, such as job ID, document ID, source path, output path, status, elapsed time, and provider name.
- Avoid giant files. Split UI, database, output management, OCR provider, queue runner, and preview behavior into separate modules.
- Avoid hidden global state. Pass configuration explicitly where reasonable.
- Keep configuration local and simple. A settings table, small config object, or `.env`-style local file is acceptable if needed.
- Add comments only when they clarify non-obvious behavior.

## 5. Windows Compatibility Rules

- Support Windows paths throughout the app.
- Handle spaces in paths.
- Handle Unicode folder and file names, including examples such as `Lycée` and `1ère Bac`.
- Use `pathlib.Path.resolve()` and `Path.relative_to()` carefully.
- Do not assume POSIX path separators.
- Handle Windows path length risks.
- Sanitize filenames only when necessary for filesystem safety.
- Never destroy or obscure original names without storing a mapping.
- If output paths must be shortened, write `output_mapping.json` at the output root.
- The mapping must preserve enough information to trace every output back to the original PDF.
- Do not delete, rename, or modify source PDFs.

## 6. GPU/Performance Rules

- Default to sequential processing.
- Provide a low VRAM safe mode suitable for a 16 GB VRAM GPU.
- The target machine has an NVIDIA RTX 5070 Ti with 16 GB VRAM.
- Avoid loading multiple OCR models at the same time.
- Avoid processing multiple PDFs concurrently unless the user explicitly enables it later.
- Release GPU memory between documents when possible.
- Clear provider/model caches only when doing so is safe and useful.
- Log processing time per document.
- Log model/provider initialization time when useful.
- Failed documents should be retryable.
- Do not let a single large or broken PDF stop the entire batch.
- Prefer predictable memory use over maximum throughput for the MVP.

## 7. Output Rules

The output folder must mirror the input folder. Never flatten output files.

For every source PDF:

1. Compute the PDF path relative to the selected input root.
2. Recreate that relative parent folder under the selected output root.
3. Create one output directory named after the PDF stem.
4. Write all generated files for that PDF inside that directory.

Each processed PDF should produce:

```text
file.md
file.html
metadata.json
processing.log
images/
```

Use the source PDF stem for `file.md` and `file.html`. If the stem contains characters that are unsafe for Windows output filenames, sanitize only the generated output filename/directory as needed and record the mapping.

Required example:

```text
Input root:
D:/PDF_INPUT/

PDF:
D:/PDF_INPUT/Maroc/Lycée/1ère Bac/Anglais/Test 1/file.pdf

Output root:
D:/OCR_OUTPUT/

Generated output:
D:/OCR_OUTPUT/Maroc/Lycée/1ère Bac/Anglais/Test 1/file/
  - file.md
  - file.html
  - metadata.json
  - processing.log
  - images/
```

If Windows path length becomes a problem, create safe shortened paths only for the affected outputs. When any path is shortened, create this file at the output root:

```text
output_mapping.json
```

`output_mapping.json` must map:

- `original_pdf_path`
- `relative_input_path`
- `mirrored_output_path`
- `markdown_path`
- `html_path`
- `status`

Do not overwrite existing output silently. Use an explicit overwrite setting, versioned output directory, or clear UI warning before replacing existing files.

## 8. UI Rules

Build a simple practical Streamlit UI for local batch work.

Required UI behavior:

- Input folder selector
- Output folder selector
- Recursive PDF scan action
- Select all PDFs
- Select individual PDFs
- Queue selected PDFs
- Batch progress bar
- Per-document progress/status where available
- Batch table with document path, status, output path, elapsed time, and error summary
- Status filters for queued, running, completed, failed, cancelled, and interrupted documents
- Document detail view
- PDF preview on the left
- Rendered Markdown or HTML preview on the right
- Raw Markdown tab
- Retry failed jobs/documents
- Open output folder button if feasible on Windows
- Offline mode toggle
- Model availability status

Keep the interface direct and utilitarian. Do not build authentication, account screens, cloud sync, deployment settings, or multi-user administration for the MVP.

## 9. Database Rules

Use SQLite for job persistence. The default database path is:

```text
data/jobs.db
```

Suggested entities/tables:

### jobs

Tracks a batch run.

Suggested fields:

- `id`
- `input_root`
- `output_root`
- `status`
- `created_at`
- `started_at`
- `finished_at`
- `offline_mode`
- `provider`
- `total_documents`
- `completed_documents`
- `failed_documents`
- `cancelled_documents`

### documents

Tracks each PDF in a job.

Suggested fields:

- `id`
- `job_id`
- `original_pdf_path`
- `relative_input_path`
- `mirrored_output_path`
- `markdown_path`
- `html_path`
- `metadata_path`
- `log_path`
- `status`
- `error_text`
- `created_at`
- `started_at`
- `finished_at`
- `elapsed_seconds`
- `retry_count`

### processing_events or logs

Tracks status transitions and important processing messages.

Suggested fields:

- `id`
- `job_id`
- `document_id`
- `level`
- `event_type`
- `message`
- `created_at`
- `details_json`

### settings

Stores local app settings.

Suggested fields:

- `key`
- `value`
- `updated_at`

Required document/job status values:

- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`
- `interrupted`

Status transitions should be explicit and persisted. After app restart, any document or job left in `running` should be marked `interrupted` unless there is a verified active runner.

## 10. Error Handling Rules

- Never crash the full batch because one PDF fails.
- Catch exceptions per document in the queue runner.
- Store readable error text in SQLite.
- Write detailed errors to `processing.log`.
- Show readable errors in the UI.
- Allow failed documents to be retried.
- Preserve the original failed output directory for diagnosis unless the user explicitly overwrites or clears it.
- Mark interrupted jobs/documents after restart.
- Missing model files in offline mode must produce this clear error:

```text
Model is not downloaded yet. Connect to internet once and run setup.
```

- Invalid input/output folders should produce actionable UI errors.
- Permission errors should identify the path that could not be read or written.
- Path length errors should trigger shortened output path handling when feasible and write `output_mapping.json`.

## 11. Setup Commands

Common local setup commands:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app/main.py
```

Internet is allowed during initial dependency installation and Chandra OCR model download. After setup, offline mode must use local files only.

## 12. Testing Instructions

Add focused tests for the behavior that protects user data and batch reliability.

Required test areas:

- Mirrored output path generation from nested input folders
- Preservation of Unicode path components
- Filename/path sanitization
- Long path fallback and `output_mapping.json` creation
- Queue status transitions
- SQLite persistence for jobs, documents, processing events/logs, and settings
- Offline mode missing model error:

```text
Model is not downloaded yet. Connect to internet once and run setup.
```

- Failed PDF does not stop the batch
- Failed document can be retried
- Running jobs/documents are marked `interrupted` after restart
- Output files are not overwritten silently

Prefer tests that isolate core logic from Streamlit. Path generation, database behavior, queue transitions, and provider availability checks should be testable without launching the UI.

## 13. Definition of Done

The MVP is done when:

- The app scans nested folders for PDFs.
- The user can select all or selected PDFs.
- The app queues selected PDFs.
- The app processes selected PDFs sequentially by default.
- Batch progress and per-document status are visible in the UI.
- The output tree mirrors the input tree.
- Markdown files are saved.
- HTML files are saved.
- Metadata JSON files are saved.
- Per-document processing logs are saved.
- Extracted images are saved under each document's `images/` directory when available.
- PDF preview works on the left.
- Rendered Markdown or HTML preview works on the right.
- Raw Markdown tab works.
- Failed PDFs are logged and do not stop the batch.
- Failed documents can be retried.
- SQLite persists jobs and document status.
- Offline mode works after setup.
- Missing local model files in offline mode show a clear setup error.

## 14. Things Codex Must Avoid

- Do not replace Streamlit with React unless explicitly asked.
- Do not introduce Docker for the MVP.
- Do not introduce Celery.
- Do not introduce Redis.
- Do not use cloud services.
- Do not call external APIs in offline mode.
- Do not upload files anywhere.
- Do not hardcode absolute paths.
- Do not delete source PDFs.
- Do not rename or modify source PDFs.
- Do not overwrite outputs silently.
- Do not flatten output folders.
- Do not ignore Windows path issues.
- Do not assume ASCII-only paths.
- Do not make vLLM required.
- Do not add authentication.
- Do not add multi-user features.
- Do not overengineer the queue, database, or provider system.
