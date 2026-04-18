from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def open_folder(path: Path) -> Path:
    target = path.expanduser().resolve()
    is_existing_file = target.exists() and target.is_file()
    folder = target.parent if is_existing_file else target
    folder.mkdir(parents=True, exist_ok=True)

    if sys.platform.startswith("win"):
        try:
            command = ["explorer.exe", f"/select,{target}"] if is_existing_file else ["explorer.exe", str(folder)]
            subprocess.Popen(command)
        except OSError:
            os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])

    return folder
