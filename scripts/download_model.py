from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Chandra OCR model files for offline use.")
    parser.add_argument("--repo-id", default="datalab-to/chandra-ocr-2", help="Hugging Face model repo id.")
    parser.add_argument("--local-dir", default="models/chandra-ocr-2", help="Local model folder.")
    parser.add_argument("--revision", default=None, help="Optional model revision.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    local_dir = Path(args.local_dir).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = snapshot_download(
        repo_id=args.repo_id,
        revision=args.revision,
        local_dir=str(local_dir),
    )

    manifest = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "local_dir": str(local_dir),
        "snapshot_path": snapshot_path,
    }
    (local_dir / "download_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Downloaded {args.repo_id} to {local_dir}")


if __name__ == "__main__":
    main()

