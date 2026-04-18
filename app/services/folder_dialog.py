from __future__ import annotations

from pathlib import Path


def choose_folder(initial_dir: str | None = None) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    initial = str(Path(initial_dir).expanduser()) if initial_dir else str(Path.cwd())
    try:
        selected = filedialog.askdirectory(initialdir=initial)
    finally:
        root.destroy()
    return selected or None

