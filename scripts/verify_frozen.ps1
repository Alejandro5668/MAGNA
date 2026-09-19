# Blocking frozen-exe verification for module-semantic-prefilter (state.yaml:
# user_decisions.pyinstaller_verification = blocking).
#
# Verifies chromadb + onnxruntime are correctly bundled and runnable INSIDE a
# real PyInstaller-built MAGNA.exe: cold run (model download), warm run (no
# download), and a non-regression `status` boot.
#
# Isolation: HOME/USERPROFILE point at a fresh temp dir for the whole script,
# so ~/.mycontext/ctx_bd.db and CHROMA_PATH (both keyed off Path.home()) never
# touch the real user store, and the cold-cache path is genuinely exercised.

$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Uses this repo's .venv (not the bare `py` launcher): PyInstaller and the
# rest of the toolchain live there, not on the system interpreter.
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "FAIL: $Py not found" -ForegroundColor Red; exit 1 }

$TempHome = Join-Path $env:TEMP ("magna_verify_frozen_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempHome -Force | Out-Null
$env:HOME = $TempHome
$env:USERPROFILE = $TempHome
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
# Pre-existing landmine (not introduced by this change): main.py's init_db()
# prints a checkmark glyph via Rich's legacy Windows console path, which
# queries the raw console output codepage rather than PYTHONIOENCODING. On a
# fresh non-UTF8 console (e.g. cp1252) this raises UnicodeEncodeError and
# crashes the frozen exe on first run. Force the console codepage to UTF-8
# for this verification session.
chcp 65001 | Out-Null

Write-Host "== verify_frozen: temp HOME = $TempHome =="

function Fail($msg) {
    Write-Host "FAIL: $msg" -ForegroundColor Red
    exit 1
}

# 1. Install deps
Write-Host "== [1/6] pip install -r requirements.txt =="
& $Py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

# 2. Build
Write-Host "== [2/6] PyInstaller ctx.spec --noconfirm =="
& $Py -m PyInstaller ctx.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller build failed" }

$ExePath = Join-Path $RepoRoot "dist\MAGNA.exe"
if (-not (Test-Path $ExePath)) { Fail "dist\MAGNA.exe not found after build" }

# Runs the exe with real file redirection (not a PowerShell pipe) so the
# child process is never attached to a live console — this avoids Rich's
# legacy-Windows-console renderer entirely (see chcp note above; belt and
# suspenders) and gives PowerShell a plain exit code instead of wrapping
# stderr lines as NativeCommandError under Stop/Continue semantics.
function Invoke-Magna($MagnaArgs, $Label) {
    $outFile = Join-Path $TempHome ("out_" + $Label + ".txt")
    $errFile = Join-Path $TempHome ("err_" + $Label + ".txt")
    $p = Start-Process -FilePath $ExePath -ArgumentList $MagnaArgs -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $out = if (Test-Path $outFile) { Get-Content $outFile -Raw -ErrorAction SilentlyContinue } else { "" }
    $err = if (Test-Path $errFile) { Get-Content $errFile -Raw -ErrorAction SilentlyContinue } else { "" }
    return @{ ExitCode = $p.ExitCode; Out = "$out`n$err" }
}

# 3. Cold run — first embed-selftest triggers the ONNX model download
Write-Host "== [3/6] dist\MAGNA.exe embed-selftest (cold) =="
$cold = Invoke-Magna "embed-selftest" "cold"
Write-Host $cold.Out
if ($cold.ExitCode -ne 0) { Fail "cold embed-selftest exited non-zero ($($cold.ExitCode))" }
if ($cold.Out -notmatch "top-1: auth") { Fail "cold run did not print 'top-1: auth'" }

# 4. Warm run — same temp HOME, model cache already populated, no download expected
Write-Host "== [4/6] dist\MAGNA.exe embed-selftest (warm) =="
$warm = Invoke-Magna "embed-selftest" "warm"
Write-Host $warm.Out
if ($warm.ExitCode -ne 0) { Fail "warm embed-selftest exited non-zero ($($warm.ExitCode))" }
if ($warm.Out -notmatch "top-1: auth") { Fail "warm run did not print 'top-1: auth'" }
if ($warm.Out -match "onnx\.tar\.gz") { Fail "warm run re-downloaded the ONNX model (expected cache hit)" }

# 5. Multi-agent task graph — blocking gate for task-context-multiagent
# (langgraph/langchain/langchain-anthropic bundled correctly, create_agent/
# StateGraph import+compile+cold-invoke inside the frozen exe, no network).
Write-Host "== [5/6] dist\MAGNA.exe graph-selftest =="
$graph = Invoke-Magna "graph-selftest" "graph"
Write-Host $graph.Out
if ($graph.ExitCode -ne 0) { Fail "graph-selftest exited non-zero ($($graph.ExitCode))" }
if ($graph.Out -notmatch "OK") { Fail "graph-selftest did not print 'OK'" }

# 6. Non-regression: the binary still boots normally
Write-Host "== [6/6] dist\MAGNA.exe status =="
$statusRun = Invoke-Magna "status" "status"
Write-Host $statusRun.Out
if ($statusRun.ExitCode -ne 0) { Fail "dist\MAGNA.exe status exited non-zero ($($statusRun.ExitCode))" }

Write-Host "== verify_frozen: PASS - all 6 steps exited 0, cold+warm both top-1 auth, warm had no download line, graph-selftest OK ==" -ForegroundColor Green

Remove-Item -Recurse -Force $TempHome -ErrorAction SilentlyContinue
exit 0
