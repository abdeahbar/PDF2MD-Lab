from __future__ import annotations

import subprocess

from app.services import folder_dialog


POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def test_choose_folder_uses_windows_sta_subprocess(monkeypatch, tmp_path):
    calls: dict[str, object] = {}
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir()

    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.shutil, "which", lambda name: POWERSHELL)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["command"] = command
        calls["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout=f"{selected_dir}\n", stderr="")

    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    chosen = folder_dialog.choose_folder(str(tmp_path), title="Select input folder")

    assert chosen == str(selected_dir)
    assert "-STA" in calls["command"]
    assert "-Command" in calls["command"]
    env = calls["env"]
    assert isinstance(env, dict)
    assert env["CHANDRA_FOLDER_DIALOG_INITIAL"] == str(tmp_path.resolve())
    assert env["CHANDRA_FOLDER_DIALOG_TITLE"] == "Select input folder"


def test_choose_folder_returns_none_when_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.shutil, "which", lambda name: POWERSHELL)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")

    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    assert folder_dialog.choose_folder(str(tmp_path)) is None


def test_choose_folder_returns_none_off_windows(monkeypatch):
    monkeypatch.setattr(folder_dialog.sys, "platform", "linux")

    assert folder_dialog.choose_folder() is None
