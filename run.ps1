param(
    [switch]$NoBrowser,
    [ValidateRange(1,65535)][int]$Port = 8000
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11 이상을 설치하세요." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "의존성 설치 실패" }
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
$LauncherArgs = @("-m", "scripts.start", "--port", "$Port")
if ($NoBrowser) { $LauncherArgs += "--no-browser" }
& .\.venv\Scripts\python.exe @LauncherArgs
if ($LASTEXITCODE -ne 0) { throw "플랫폼 실행 실패. 위 오류 내용을 확인하세요." }
