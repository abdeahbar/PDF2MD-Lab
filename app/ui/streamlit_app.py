from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.core.config import AppConfig, load_config
from app.core.queue_manager import QueueManager
from app.db.storage import JobStore
from app.models.job import JobRecord, JobStatus, OCRSettings
from app.services.discovery import discover_pdfs
from app.services.folder_dialog import choose_folder
from app.services.model_cache import check_model_availability
from app.services.preview import get_pdf_page_count, read_text_file, render_pdf_page_png
from app.services.windows import open_folder
from app.utils.logging import configure_logging
from app.utils.paths import resolve_project_path


st.set_page_config(
    page_title="Chandra Batch OCR",
    page_icon="CH",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid #e6e8eb;
            border-radius: 0.5rem;
            padding: 0.75rem 0.9rem;
            background: #ffffff;
        }
        .small-muted {
            color: #667085;
            font-size: 0.88rem;
        }
        .status-pill {
            display: inline-block;
            padding: 0.1rem 0.45rem;
            border-radius: 0.45rem;
            border: 1px solid #d0d5dd;
            font-size: 0.8rem;
            color: #344054;
            background: #f9fafb;
        }
        .copy-button {
            border: 1px solid #cfd7e3;
            background: #ffffff;
            color: #111827;
            border-radius: 0.45rem;
            padding: 0.5rem 0.8rem;
            min-height: 44px;
            cursor: pointer;
            font: 14px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        .copy-button:hover {
            background: #f3f6fa;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_resources() -> tuple[AppConfig, JobStore, QueueManager]:
    config = load_config()
    configure_logging(config.logs_dir)
    store = JobStore(config.db_path)
    store.initialize()
    if store.get_value("ocr_settings") is None:
        store.save_ocr_settings(config.ocr_settings)
    if store.get_value("output_folder") is None:
        store.set_value("output_folder", str(config.output_dir))
    store.mark_interrupted_jobs()
    manager = QueueManager(store)
    return config, store, manager


def format_elapsed(seconds: float | None) -> str:
    seconds = int(seconds or 0)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def selected_rows(event: Any) -> list[int]:
    try:
        return list(event.selection.rows)
    except Exception:
        if isinstance(event, dict):
            return list(event.get("selection", {}).get("rows", []))
    return []


def copy_markdown_button(markdown_text: str) -> None:
    payload = json.dumps(markdown_text)
    components.html(
        f"""
        <button
            style='border:1px solid #cfd7e3;background:#fff;color:#111827;border-radius:0.45rem;padding:0.5rem 0.8rem;min-height:44px;cursor:pointer;font:14px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
            onclick='navigator.clipboard.writeText({payload}); this.innerText="Copied";'>
            Copy markdown
        </button>
        """,
        height=56,
    )


def render_sidebar(config: AppConfig, store: JobStore) -> tuple[str, str, OCRSettings, bool]:
    st.sidebar.header("Folders")

    input_default = store.get_value("input_folder", "")
    output_default = store.get_value("output_folder", str(config.output_dir))

    input_col, input_browse_col = st.sidebar.columns([4, 1])
    input_folder = input_col.text_input("Input folder", value=input_default or "", placeholder="C:\\path\\to\\pdfs")
    if input_browse_col.button("...", key="browse_input", help="Browse for input folder"):
        selected = choose_folder(input_folder or str(ROOT))
        if selected:
            store.set_value("input_folder", selected)
            st.rerun()

    output_col, output_browse_col = st.sidebar.columns([4, 1])
    output_folder = output_col.text_input("Output folder", value=output_default, placeholder="outputs")
    if output_browse_col.button("...", key="browse_output", help="Browse for output folder"):
        selected = choose_folder(output_folder or str(config.output_dir))
        if selected:
            store.set_value("output_folder", selected)
            st.rerun()

    store.set_value("input_folder", input_folder)
    store.set_value("output_folder", output_folder)

    if st.sidebar.button("Open output folder", use_container_width=True):
        open_folder(resolve_project_path(output_folder))

    st.sidebar.divider()
    st.sidebar.header("Settings")

    saved_settings = store.get_ocr_settings()
    method = st.sidebar.selectbox("Chandra method", ["hf"], index=0, help="HF local inference is the MVP default.")
    safe_mode = st.sidebar.toggle("Safe mode for 16 GB GPU", value=saved_settings.safe_mode)
    batch_size = st.sidebar.number_input(
        "Batch size",
        min_value=1,
        max_value=4,
        value=int(saved_settings.batch_size),
        step=1,
        help="Chandra defaults to 1 page per batch for HF. Keep this low on 16 GB GPUs.",
    )
    max_parallel_jobs = st.sidebar.number_input(
        "Max parallel jobs",
        min_value=1,
        max_value=2,
        value=int(saved_settings.max_parallel_jobs),
        step=1,
        disabled=safe_mode,
        help="Safe mode forces one job at a time.",
    )
    include_images = st.sidebar.checkbox("Extract images", value=saved_settings.include_images)
    include_headers_footers = st.sidebar.checkbox(
        "Include headers/footers",
        value=saved_settings.include_headers_footers,
    )
    page_range = st.sidebar.text_input(
        "Page range",
        value=saved_settings.page_range or "",
        placeholder="Optional, e.g. 1-5,7",
    )
    max_output_tokens = st.sidebar.number_input(
        "Max output tokens",
        min_value=0,
        max_value=65536,
        value=int(saved_settings.max_output_tokens or 12384),
        step=512,
        help="Set to 0 to let Chandra use its default.",
    )
    offline_mode = st.sidebar.toggle("Offline mode", value=saved_settings.offline_mode)
    model_checkpoint = st.sidebar.text_input("Setup model repo", value=saved_settings.model_checkpoint)
    local_model_path = st.sidebar.text_input("Local model path", value=saved_settings.local_model_path)

    settings = OCRSettings(
        method=method,
        batch_size=int(batch_size),
        max_parallel_jobs=int(max_parallel_jobs),
        safe_mode=safe_mode,
        include_images=include_images,
        include_headers_footers=include_headers_footers,
        page_range=page_range,
        max_output_tokens=int(max_output_tokens) if max_output_tokens else None,
        offline_mode=offline_mode,
        model_checkpoint=model_checkpoint,
        local_model_path=local_model_path,
    ).normalized()
    store.save_ocr_settings(settings)

    availability = check_model_availability(settings.local_model_path, settings.model_checkpoint)
    if availability.available:
        st.sidebar.success(f"Model available via {availability.source}")
        st.sidebar.caption(availability.detail)
    elif settings.offline_mode:
        st.sidebar.error(availability.detail)
    else:
        st.sidebar.warning("Model is not available locally. Disable offline mode only during first setup/download.")

    auto_refresh = st.sidebar.checkbox("Auto-refresh while queue is active", value=True)
    return input_folder, output_folder, settings, auto_refresh


def render_metrics(store: JobStore, manager: QueueManager) -> dict[str, int]:
    counts = store.count_by_status()
    total = counts.get("total", 0)
    finished = (
        counts.get(JobStatus.COMPLETED.value, 0)
        + counts.get(JobStatus.FAILED.value, 0)
        + counts.get(JobStatus.CANCELLED.value, 0)
        + counts.get(JobStatus.INTERRUPTED.value, 0)
    )

    metric_cols = st.columns(5)
    metric_cols[0].metric("Total PDFs", total)
    metric_cols[1].metric("Completed", counts.get(JobStatus.COMPLETED.value, 0))
    metric_cols[2].metric("Failed", counts.get(JobStatus.FAILED.value, 0))
    metric_cols[3].metric("Running", counts.get(JobStatus.RUNNING.value, 0))
    metric_cols[4].metric("Queued", counts.get(JobStatus.QUEUED.value, 0))

    progress = finished / total if total else 0
    st.progress(progress, text=f"Batch progress: {finished}/{total} finished")
    st.caption(
        f"Workers: {manager.worker_count()} | Queue is {'paused' if manager.paused else 'ready'}"
    )
    return counts


def render_controls(store: JobStore, manager: QueueManager, settings: OCRSettings) -> None:
    start_col, pause_col, resume_col, cancel_col, retry_col = st.columns(5)
    if start_col.button("Start", type="primary", use_container_width=True):
        manager.start(settings.max_parallel_jobs)
        st.rerun()
    if pause_col.button("Pause queue", use_container_width=True):
        manager.pause()
        st.rerun()
    if resume_col.button("Resume queue", use_container_width=True):
        manager.resume()
        manager.start(settings.max_parallel_jobs)
        st.rerun()
    if cancel_col.button("Cancel current", use_container_width=True):
        cancelled = manager.cancel_current()
        if cancelled == 0:
            st.toast("No running job to cancel.")
        st.rerun()
    if retry_col.button("Retry failed", use_container_width=True):
        retry_count = store.retry_failed_jobs()
        if retry_count:
            manager.start(settings.max_parallel_jobs)
        st.toast(f"Queued {retry_count} job(s) for retry.")
        st.rerun()
    st.caption("Pause stops the queue from claiming new jobs. It does not stop the active OCR process.")


def render_discovery(input_folder: str, output_folder: str, settings: OCRSettings, store: JobStore) -> None:
    st.subheader("Input PDFs")
    discover_col, queue_col = st.columns([1, 1])
    if discover_col.button("Scan input folder", use_container_width=True):
        try:
            if not input_folder.strip():
                raise ValueError("Choose an input folder before scanning.")
            discovered = discover_pdfs(resolve_project_path(input_folder))
        except Exception as exc:
            st.error(str(exc))
            discovered = []
        st.session_state["discovered_pdfs"] = [
            {
                "Select": True,
                "File": item.path.name,
                "Pages": item.page_count,
                "Size MB": item.size_mb,
                "Path": str(item.path),
            }
            for item in discovered
        ]

    discovered_rows = st.session_state.get("discovered_pdfs", [])
    if not discovered_rows:
        st.info("Choose an input folder and scan to find PDFs recursively.")
        return

    discovered_df = pd.DataFrame(discovered_rows)
    edited_df = st.data_editor(
        discovered_df,
        hide_index=True,
        use_container_width=True,
        disabled=["File", "Pages", "Size MB", "Path"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "Path": st.column_config.TextColumn("Path", width="large"),
        },
        key="discovered_editor",
    )
    selected_paths = [Path(row["Path"]) for _, row in edited_df.iterrows() if bool(row["Select"])]

    if queue_col.button("Add selected PDFs to queue", use_container_width=True, disabled=not selected_paths):
        try:
            if not input_folder.strip():
                raise ValueError("Choose an input folder before queueing PDFs.")
            if not output_folder.strip():
                raise ValueError("Choose an output folder before queueing PDFs.")
            created = store.add_jobs(
                selected_paths,
                resolve_project_path(input_folder),
                resolve_project_path(output_folder),
                settings,
            )
        except Exception as exc:
            st.error(str(exc))
            return
        st.success(f"Queued {len(created)} PDF(s). Use Start to begin processing.")
        st.rerun()


def jobs_dataframe(jobs: list[JobRecord]) -> pd.DataFrame:
    rows = []
    for job in jobs:
        page_total = job.page_count if job.page_count is not None else ""
        progress_text = f"{job.processed_pages}/{page_total}" if page_total != "" else str(job.processed_pages)
        rows.append(
            {
                "id": job.id,
                "Filename": job.filename,
                "Status": job.status,
                "Pages": page_total,
                "Processed": progress_text,
                "Elapsed": format_elapsed(job.elapsed_seconds),
                "Output": str(job.output_dir),
                "Error": job.error_text or "",
            }
        )
    return pd.DataFrame(rows)


def render_active_document(store: JobStore) -> None:
    running = store.get_running_jobs()
    if not running:
        return
    active = running[0]
    st.subheader("Active Document")
    progress = active.progress_fraction if active.page_count else 0.05
    label = f"{active.filename} | {active.processed_pages}/{active.page_count or '?'} pages | {format_elapsed(active.elapsed_seconds)}"
    st.progress(progress, text=label)


def render_jobs(store: JobStore) -> JobRecord | None:
    st.subheader("Queue")
    status_options = [
        "all",
        JobStatus.QUEUED.value,
        JobStatus.RUNNING.value,
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
        JobStatus.INTERRUPTED.value,
    ]
    status_filter = st.radio("Filter", status_options, horizontal=True, label_visibility="collapsed")
    jobs = store.list_jobs(None if status_filter == "all" else status_filter)
    if not jobs:
        st.info("No jobs in this filter.")
        return None

    table_df = jobs_dataframe(jobs)
    event = st.dataframe(
        table_df,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={"id": None, "Output": st.column_config.TextColumn("Output", width="large")},
    )
    rows = selected_rows(event)
    if rows:
        st.session_state["selected_job_id"] = table_df.iloc[rows[0]]["id"]

    selected_job_id = st.session_state.get("selected_job_id")
    if selected_job_id:
        try:
            return store.get_job(selected_job_id)
        except KeyError:
            st.session_state.pop("selected_job_id", None)

    labels = [f"{job.filename} ({job.status})" for job in jobs]
    selected_label = st.selectbox("Inspect document", labels, index=0)
    return jobs[labels.index(selected_label)]


def render_html_preview(html_text: str) -> None:
    if not html_text:
        st.info("HTML output is not available yet.")
        return
    components.html(
        f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                line-height: 1.5;
                color: #111827;
                margin: 0;
                padding: 1rem;
            }}
            img {{ max-width: 100%; height: auto; }}
            table {{ border-collapse: collapse; width: 100%; }}
            td, th {{ border: 1px solid #d0d5dd; padding: 0.35rem; vertical-align: top; }}
            pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
          </style>
        </head>
        <body>{html_text}</body>
        </html>
        """,
        height=720,
        scrolling=True,
    )


def render_detail(job: JobRecord | None) -> None:
    if job is None:
        return

    st.subheader("Document Detail")
    st.markdown(
        f'<span class="status-pill">{job.status}</span> <span class="small-muted">{job.source_pdf}</span>',
        unsafe_allow_html=True,
    )
    if job.error_text:
        st.error(job.error_text)

    left, right = st.columns([0.9, 1.1], gap="large")
    with left:
        st.markdown("**PDF preview**")
        page_count = job.page_count or get_pdf_page_count(job.source_pdf) or 1
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=max(1, page_count),
            value=1,
            step=1,
            key=f"page_{job.id}",
        )
        try:
            png = render_pdf_page_png(str(job.source_pdf), int(page_number) - 1)
            st.image(png, use_container_width=True)
        except Exception as exc:
            st.warning(str(exc))

    with right:
        open_col, path_col = st.columns([1, 3])
        if open_col.button("Open output", key=f"open_{job.id}", use_container_width=True):
            open_folder(job.output_dir)
        path_col.caption(str(job.output_dir))

        markdown_text = read_text_file(job.markdown_path, limit_chars=500_000)
        html_text = read_text_file(job.html_path, limit_chars=500_000)
        metadata_text = read_text_file(job.metadata_path, limit_chars=200_000)
        log_text = read_text_file(job.log_path, limit_chars=200_000)

        if not markdown_text and job.status not in {JobStatus.COMPLETED.value, JobStatus.FAILED.value}:
            st.info("Output preview will appear as soon as the document finishes.")

        html_tab, md_tab, raw_tab, metadata_tab, log_tab = st.tabs(
            ["HTML", "Markdown", "Raw markdown", "Metadata", "Logs"]
        )
        with html_tab:
            render_html_preview(html_text)
        with md_tab:
            if markdown_text:
                st.markdown(markdown_text)
            else:
                st.info("Markdown output is not available yet.")
        with raw_tab:
            if markdown_text:
                copy_markdown_button(markdown_text)
                st.code(markdown_text, language="markdown")
            else:
                st.info("Raw markdown is not available yet.")
        with metadata_tab:
            if metadata_text:
                try:
                    st.json(json.loads(metadata_text))
                except json.JSONDecodeError:
                    st.code(metadata_text, language="json")
            else:
                st.info("Metadata is not available yet.")
        with log_tab:
            st.code(log_text or "No log output yet.", language="text")


def main() -> None:
    inject_css()
    config, store, manager = get_resources()
    input_folder, output_folder, settings, auto_refresh = render_sidebar(config, store)

    st.title("Chandra Batch OCR")
    st.caption("Local-first PDF OCR queue for Windows. Chandra HF is the active provider; vLLM is left for a future optional mode.")

    counts = render_metrics(store, manager)
    render_controls(store, manager, settings)

    st.divider()
    top_left, top_right = st.columns([1, 1], gap="large")
    with top_left:
        render_discovery(input_folder, output_folder, settings, store)
    with top_right:
        render_active_document(store)

    st.divider()
    selected_job = render_jobs(store)
    render_detail(selected_job)

    queue_active = counts.get(JobStatus.RUNNING.value, 0) > 0 or counts.get(JobStatus.QUEUED.value, 0) > 0
    if auto_refresh and queue_active:
        time.sleep(max(1, int(config.refresh_seconds)))
        st.rerun()


if __name__ == "__main__":
    main()
