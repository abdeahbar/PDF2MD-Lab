from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.job import DEFAULT_MODEL_REPO
from app.utils.paths import resolve_project_path


@dataclass(slots=True)
class ModelAvailability:
    available: bool
    source: str
    detail: str


def _looks_like_model_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    required = ["config.json"]
    has_required = all((path / name).exists() for name in required)
    has_weights = any(path.glob("*.safetensors")) or any(path.glob("*.bin"))
    has_processor = any((path / name).exists() for name in ("preprocessor_config.json", "processor_config.json", "tokenizer_config.json"))
    return has_required and has_weights and has_processor


def _is_cached_in_hf(repo_id: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False

    try:
        cached: Any = try_to_load_from_cache(repo_id, "config.json")
    except Exception:
        return False
    return isinstance(cached, str) and Path(cached).exists()


def check_model_availability(local_model_path: str, repo_id: str = DEFAULT_MODEL_REPO) -> ModelAvailability:
    local_path = resolve_project_path(local_model_path)
    if _looks_like_model_dir(local_path):
        return ModelAvailability(True, "local folder", str(local_path))

    if _is_cached_in_hf(repo_id):
        return ModelAvailability(True, "Hugging Face cache", repo_id)

    return ModelAvailability(
        False,
        "missing",
        "Model is not downloaded yet. Connect to internet once and run setup.",
    )
