from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def get_pdf_page_count(pdf_path: Path) -> int | None:
    try:
        import fitz
    except ImportError:
        return None

    try:
        with fitz.open(pdf_path) as document:
            return int(document.page_count)
    except Exception:
        return None


@lru_cache(maxsize=128)
def render_pdf_page_png(pdf_path_text: str, page_index: int, zoom: float = 1.4) -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is not installed. Run pip install -r requirements.txt.") from exc

    pdf_path = Path(pdf_path_text)
    with fitz.open(pdf_path) as document:
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError("Selected page is outside the PDF page range.")
        page = document.load_page(page_index)
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return pixmap.tobytes("png")


def read_text_file(path: Path | None, limit_chars: int | None = None) -> str:
    if not path or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit_chars and len(text) > limit_chars:
        return text[:limit_chars] + "\n\n[Preview truncated]"
    return text

