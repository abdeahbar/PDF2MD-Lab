from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
import re


_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
MAX_SAFE_WINDOWS_PATH = 240


@dataclass(slots=True)
class OutputPathPlan:
    output_dir: Path
    relative_pdf_path: Path
    shortened: bool = False


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_project_path(path_text: str | Path) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = project_root() / path
    return path.resolve()


def clean_name(value: str, fallback: str = "document", max_length: int = 80) -> str:
    cleaned = _WINDOWS_UNSAFE.sub("_", value.strip()).strip(" ._-")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:max_length].rstrip(" ._-") or fallback


def short_path_hash(path: Path) -> str:
    return sha1(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:8]


def relative_to_input_root(pdf_path: Path, input_root: Path) -> Path:
    try:
        return pdf_path.resolve().relative_to(input_root.resolve())
    except ValueError:
        return Path(pdf_path.name)


def clean_relative_parent(relative_path: Path) -> Path:
    parent_parts = [clean_name(part, fallback="folder", max_length=120) for part in relative_path.parent.parts]
    return Path(*parent_parts) if parent_parts else Path()


def _versioned_dir(parent: Path, base: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / base
    if not candidate.exists():
        return candidate

    for index in range(2, 1000):
        versioned = parent / f"{base}_v{index}"
        if not versioned.exists():
            return versioned
    raise RuntimeError(f"Could not find an unused output folder under {parent}")


def build_output_path_plan(output_root: Path, input_root: Path, pdf_path: Path) -> OutputPathPlan:
    output_root.mkdir(parents=True, exist_ok=True)
    relative_pdf = relative_to_input_root(pdf_path, input_root)
    relative_parent = clean_relative_parent(relative_pdf)
    base = clean_name(pdf_path.stem)
    target_parent = output_root / relative_parent
    candidate = target_parent / base
    shortened = False

    if len(str(candidate)) > MAX_SAFE_WINDOWS_PATH:
        shortened = True
        target_parent = output_root / "_shortened" / short_path_hash(pdf_path)
        base = clean_name(pdf_path.stem, max_length=48)

    return OutputPathPlan(
        output_dir=_versioned_dir(target_parent, base),
        relative_pdf_path=relative_pdf,
        shortened=shortened,
    )

