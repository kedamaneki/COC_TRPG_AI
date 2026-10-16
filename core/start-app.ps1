param([int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv-app\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Missing .venv-app. See APP_STARTUP.md.' }
Push-Location (Join-Path $PSScriptRoot 'src')
try {
    & $pythonPath -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
    if ($LASTEXITCODE -ne 0) { throw "Streamlit exited with code $LASTEXITCODE" }
} finally { Pop-Location }
