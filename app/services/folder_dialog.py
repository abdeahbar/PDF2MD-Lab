from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys


logger = logging.getLogger(__name__)

_WINDOWS_FOLDER_DIALOG_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms

$initial = $env:CHANDRA_FOLDER_DIALOG_INITIAL
$title = $env:CHANDRA_FOLDER_DIALOG_TITLE
if ([string]::IsNullOrWhiteSpace($title)) {
    $title = "Select folder"
}
if ([string]::IsNullOrWhiteSpace($initial) -or -not (Test-Path -LiteralPath $initial -PathType Container)) {
    $initial = [Environment]::GetFolderPath("MyDocuments")
}

$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.StartPosition = "CenterScreen"
$owner.Width = 1
$owner.Height = 1
$owner.Opacity = 0

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $title
$dialog.SelectedPath = $initial
$dialog.ShowNewFolderButton = $true

try {
    $owner.Show()
    $owner.Activate()
    $result = $dialog.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK -and -not [string]::IsNullOrWhiteSpace($dialog.SelectedPath)) {
        Write-Output $dialog.SelectedPath
    }
}
finally {
    $dialog.Dispose()
    $owner.Close()
    $owner.Dispose()
}
"""


def _existing_initial_dir(initial_dir: str | None) -> Path:
    candidate = Path(initial_dir).expanduser() if initial_dir else Path.cwd()
    try:
        candidate = candidate.resolve()
    except OSError:
        candidate = candidate.absolute()

    try:
        is_file = candidate.is_file()
    except OSError:
        is_file = False
    if is_file:
        candidate = candidate.parent

    while not _path_exists(candidate) and candidate.parent != candidate:
        candidate = candidate.parent

    if not _path_exists(candidate):
        return Path.cwd().resolve()
    return candidate


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _find_powershell() -> str | None:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable:
        return executable

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    bundled = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if bundled.exists():
        return str(bundled)
    return None


def choose_folder(initial_dir: str | None = None, title: str = "Select folder") -> str | None:
    if not sys.platform.startswith("win"):
        logger.info("Native folder picker is only implemented for Windows.")
        return None

    powershell = _find_powershell()
    if powershell is None:
        logger.warning("Could not find powershell.exe for native folder picker.")
        return None

    env = os.environ.copy()
    env["CHANDRA_FOLDER_DIALOG_INITIAL"] = str(_existing_initial_dir(initial_dir))
    env["CHANDRA_FOLDER_DIALOG_TITLE"] = title

    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _WINDOWS_FOLDER_DIALOG_SCRIPT,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except OSError:
        logger.warning("Could not open native folder picker.", exc_info=True)
        return None

    if completed.returncode != 0:
        logger.warning("Native folder picker failed: %s", completed.stderr.strip())
        return None

    selected = completed.stdout.strip()
    return selected or None
