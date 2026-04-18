from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from app.models.job import OCRSettings
from app.utils.paths import project_root, resolve_project_path


@dataclass(slots=True)
class AppConfig:
    data_dir: Path
    output_dir: Path
    logs_dir: Path
    db_path: Path
    ocr_settings: OCRSettings
    refresh_seconds: int = 2


def load_config(config_path: Path | None = None) -> AppConfig:
    root = project_root()
    config_file = config_path or (root / "config.toml")
    raw: dict = {}
    if config_file.exists():
        raw = tomllib.loads(config_file.read_text(encoding="utf-8"))

    paths = raw.get("paths", {})
    app = raw.get("app", {})
    ocr = raw.get("ocr", {})

    data_dir = resolve_project_path(paths.get("data_dir", "data"))
    output_dir = resolve_project_path(paths.get("output_dir", "outputs"))
    logs_dir = resolve_project_path(paths.get("logs_dir", "data/logs"))
    db_path = resolve_project_path(paths.get("db_path", str(data_dir / "jobs.db")))

    return AppConfig(
        data_dir=data_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        db_path=db_path,
        ocr_settings=OCRSettings.from_dict(ocr),
        refresh_seconds=int(app.get("refresh_seconds", 2)),
    )

