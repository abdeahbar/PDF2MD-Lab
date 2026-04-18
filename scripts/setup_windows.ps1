param(
    [string]$PythonCommand = "py",
    [string[]]$PythonArgs = @("-3.11"),
    [switch]$SkipWheelhouse,
    [switch]$CpuTorch,
    [string]$TorchCudaIndexUrl = "https://download.pytorch.org/whl/cu128",
    [string]$TorchVersion = "2.11.0+cu128",
    [string]$TorchVisionVersion = "0.26.0+cu128"
)

$ErrorActionPreference = "Stop"

Set-Location -Path (Split-Path -Parent $PSScriptRoot)

& $PythonCommand @PythonArgs -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

if (-not $SkipWheelhouse) {
    New-Item -ItemType Directory -Force -Path vendor\wheels | Out-Null
    & .\.venv\Scripts\python.exe -m pip download -r requirements.txt -d vendor\wheels
    if (-not $CpuTorch) {
        & .\.venv\Scripts\python.exe -m pip download "torch==$TorchVersion" "torchvision==$TorchVisionVersion" -d vendor\wheels --index-url $TorchCudaIndexUrl --extra-index-url https://pypi.org/simple
    }
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not $CpuTorch) {
    # Chandra's HF backend runs through PyTorch, so replace the default CPU wheel with CUDA.
    & .\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall "torch==$TorchVersion" "torchvision==$TorchVisionVersion" --index-url $TorchCudaIndexUrl --extra-index-url https://pypi.org/simple
}
& .\.venv\Scripts\python.exe scripts\download_model.py --repo-id datalab-to/chandra-ocr-2 --local-dir models\chandra-ocr-2

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run: .\.venv\Scripts\streamlit.exe run app\ui\streamlit_app.py"
