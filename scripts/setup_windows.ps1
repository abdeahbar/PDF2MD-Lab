param(
    [string]$PythonCommand = "py",
    [string[]]$PythonArgs = @("-3.11"),
    [switch]$SkipWheelhouse
)

$ErrorActionPreference = "Stop"

Set-Location -Path (Split-Path -Parent $PSScriptRoot)

& $PythonCommand @PythonArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

if (-not $SkipWheelhouse) {
    New-Item -ItemType Directory -Force -Path vendor\wheels | Out-Null
    & .\.venv\Scripts\python.exe -m pip download -r requirements.txt -d vendor\wheels
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe scripts\download_model.py --repo-id datalab-to/chandra-ocr-2 --local-dir models\chandra-ocr-2

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run: .\.venv\Scripts\streamlit.exe run app\ui\streamlit_app.py"

