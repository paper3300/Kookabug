# 라이선스 감사 (M0a 계획 2.8의 1~5단계). CI licenses 잡과 같은 명령이다.
# 단계 구현은 license_pipeline.py 하나에 두고 여기서는 부르기만 한다.
#   powershell -File tools/license_audit.ps1 [-BuildDir build/audit] [-NoJs]
param(
    [string]$BuildDir = "build/audit",
    [switch]$NoJs
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$uvArgs = @(
    "run", "--project", $root, "--locked", "python",
    (Join-Path $PSScriptRoot "license_pipeline.py"),
    "--project", $root,
    "--build-dir", (Join-Path $root $BuildDir)
)
if ($NoJs) { $uvArgs += "--no-js" }
& uv @uvArgs
exit $LASTEXITCODE
