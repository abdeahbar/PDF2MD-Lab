from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.preview import get_pdf_page_count


@dataclass(slots=True)
class DiscoveredPDF:
    path: Path
    page_count: int | None
    size_mb: float


def discover_pdfs(input_folder: Path) -> list[DiscoveredPDF]:
    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_folder}")
    if not input_folder.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {input_folder}")

    pdfs: list[DiscoveredPDF] = []
    for path in sorted(input_folder.rglob("*")):
        if path.is_file() and path.suffix.lower() == ".pdf":
            stat = path.stat()
            pdfs.append(
                DiscoveredPDF(
                    path=path.resolve(),
                    page_count=get_pdf_page_count(path),
                    size_mb=round(stat.st_size / (1024 * 1024), 2),
                )
            )
    return pdfs

