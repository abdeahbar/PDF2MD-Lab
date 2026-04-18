# Chandra Batch OCR MVP

A local-first Windows desktop web app for running Chandra OCR over folders of PDFs. The app uses Streamlit for the UI, SQLite for job persistence, PyMuPDF for PDF previews, and Chandra OCR with the Hugging Face method as the active backend.

The MVP is intentionally conservative for a single NVIDIA GPU with 16 GB VRAM:

- Chandra method defaults to `hf`.
- Safe mode defaults to one PDF at a time.
- Batch size defaults to 1 page.
- Offline mode defaults to on after setup.
- vLLM is not the default path and is only represented as a future provider boundary.

## Project Structure

```text
app/
  core/        queue worker and config loading
  db/          SQLite job persistence
  models/      typed job/settings models
  services/    Chandra runner, discovery, previews, model cache checks
  ui/          Streamlit app
  utils/       path and logging helpers
data/
  jobs.db      created on first run
models/
  chandra-ocr-2/  local model files after setup
outputs/
  one versioned folder per queued PDF
scripts/
  download_model.py
  setup_windows.ps1
  run_app.ps1
```

## Online Setup Once

Run these commands in PowerShell from the project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip download -r requirements.txt -d vendor\wheels
python -m pip install -r requirements.txt
python scripts\download_model.py --repo-id datalab-to/chandra-ocr-2 --local-dir models\chandra-ocr-2
```

You can also run the bundled setup script:

```powershell
.\scripts\setup_windows.ps1
```

The `pip download` step creates a local wheel cache under `vendor\wheels` so dependencies can be installed again later without internet.

## Offline Install Later

If the venv needs to be recreated while offline and `vendor\wheels` is already present:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links vendor\wheels -r requirements.txt
```

The model should already be present in:

```text
models/chandra-ocr-2/
```

## Run Command

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app\ui\streamlit_app.py
```

Or:

```powershell
.\scripts\run_app.ps1
```

Streamlit will print a local URL, usually `http://localhost:8501`.

## Usage Guide

1. Open the app.
2. In the sidebar, choose an input folder and output folder.
3. Keep `Chandra method` set to `hf`.
4. Keep `Offline mode` enabled once the model is downloaded.
5. Confirm the sidebar says the model is available locally.
6. Click `Scan input folder`.
7. Review the discovered PDFs and uncheck anything you do not want to process.
8. Click `Add selected PDFs to queue`.
9. Click `Start`.
10. Click a row in the queue table to inspect a document.
11. For completed jobs, use the detail panel to preview the PDF, HTML output, rendered Markdown, raw Markdown, metadata, and logs.
12. Use `Open output` to open that document's output folder in Windows Explorer.

## Output Layout

Each queued PDF gets its own dedicated folder under the chosen output folder. The input folder structure is mirrored under the output root. Existing folders are not overwritten silently; a new versioned folder is created when needed.

Typical output:

```text
outputs/
  ClientA/
    2026/
      invoice_001/
        invoice_001.md
        invoice_001.html
        invoice_001_metadata.json
        processing.log
        image_*.png
        images/
          image_*.png
  output_mapping.json
```

Chandra writes Markdown, HTML, metadata JSON, and extracted images when available. The app keeps logs beside the output so failed files can be diagnosed without stopping the queue. `output_mapping.json` maps each source PDF to its mirrored output folder and generated preview files.

## Offline Mode

When offline mode is enabled, the app sets:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
```

The app will use `models/chandra-ocr-2/` when it exists. If the local folder is missing but the Hugging Face cache already contains the model, Chandra can use the cache offline. If no local model is available, the UI and job log show:

```text
Model is not downloaded yet. Connect to internet once and run setup.
```

The app does not upload PDFs or outputs. In offline mode it does not call Hugging Face, Datalab API, or any external service.

## Settings

Defaults are stored in `config.sample.toml`; copy it to `config.toml` if you want project-level defaults.

Important defaults:

- `method = "hf"`
- `safe_mode = true`
- `batch_size = 1`
- `max_parallel_jobs = 1`
- `offline_mode = true`
- `model_checkpoint = "datalab-to/chandra-ocr-2"`
- `local_model_path = "models/chandra-ocr-2"`

The Streamlit sidebar saves the active settings to SQLite and each queued job stores a copy of the settings used when it was queued.

## Recovery

Job state is stored in `data/jobs.db`. If the app closes while a job is running, that job is marked `interrupted` on the next startup. Use `Retry failed` to requeue failed, cancelled, or interrupted jobs.

## Troubleshooting

### Chandra OCR is not installed

Run:

```powershell
python -m pip install -r requirements.txt
```

### Model is missing

Connect to the internet once and run:

```powershell
python scripts\download_model.py --repo-id datalab-to/chandra-ocr-2 --local-dir models\chandra-ocr-2
```

### CUDA out of memory

Keep safe mode enabled, keep batch size at 1, and keep max parallel jobs at 1. Close other GPU-heavy apps before running a batch.

### Streamlit cannot open a folder dialog

Folder browse uses a local Tk dialog. If it is blocked, paste the folder path into the text field manually.

## Implementation Notes

The Chandra HF runner uses the documented CLI shape:

```powershell
chandra input.pdf output --method hf
```

The provider abstraction is in `app/services/ocr_provider.py`. `ChandraHFProvider` is active. `ChandraVLLMProvider` is a stub for a later optional mode and is not required for this MVP.

## Future Improvements

- WSL2/vLLM mode
- folder watcher
- page-level live preview
- export bundles
- search across processed markdown

## References

- Chandra OCR GitHub documentation: https://github.com/datalab-to/chandra
- Chandra OCR package page: https://pypi.org/project/chandra-ocr/
- Chandra OCR 2 model page: https://huggingface.co/datalab-to/chandra-ocr-2
