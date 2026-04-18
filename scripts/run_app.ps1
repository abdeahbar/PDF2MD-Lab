$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)
& .\.venv\Scripts\streamlit.exe run app\ui\streamlit_app.py

