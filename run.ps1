$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 이상을 설치하세요." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "의존성 설치 실패" }
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
Write-Host "첫 실행 시 별도 터미널에서 로그인 계정을 설정하세요: .\.venv\Scripts\python.exe -m scripts.configure_auth --username admin"
Write-Host "HTTP 로컬 테스트에서만 INVESTPILOT_AUTH_SECURE_COOKIE=false를 사용하세요."
Write-Host "InvestPilot: http://127.0.0.1:8000 (종료: Ctrl+C)"
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
