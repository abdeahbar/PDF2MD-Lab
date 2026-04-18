from __future__ import annotations

from app.services import windows


def test_open_folder_uses_explorer_for_windows_directory(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    target = tmp_path / "output folder"

    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.subprocess, "Popen", lambda command: calls.append(command))

    opened = windows.open_folder(target)

    assert opened == target.resolve()
    assert opened.exists()
    assert calls == [["explorer.exe", str(opened)]]


def test_open_folder_selects_existing_file_on_windows(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    target = tmp_path / "output.md"
    target.write_text("# Output", encoding="utf-8")

    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setattr(windows.subprocess, "Popen", lambda command: calls.append(command))

    opened = windows.open_folder(target)

    assert opened == tmp_path.resolve()
    assert calls == [["explorer.exe", f"/select,{target.resolve()}"]]
