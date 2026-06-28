<#
  run.ps1 — FY3 rendering launcher for Windows
  Handles all the environment plumbing (venv, FFmpeg PATH, UTF-8) for you.

  Usage (from C:\yt_automation):
    .\run.ps1 gather --dry-run       # preview which beats would be pulled from sources
    .\run.ps1 gather                 # pull new beats from beat_sources.json into beats\
    .\run.ps1 render                 # render every beat in beats\ (render_lit.py)
    .\run.ps1 render --only army     # render specific stems
    .\run.ps1 render --force         # re-render existing
    .\run.ps1 shorts                 # render vertical Shorts (render_shorts.py)
    .\run.ps1 batch                  # run batch_ten.py (hand-picked 10)
    .\run.ps1 metadata               # generate SEO metadata for new beats
    .\run.ps1 metadata --force       # regenerate all metadata
    .\run.ps1 analyze                # detect accurate BPM + key -> metadata (beat_analysis.py)
    .\run.ps1 analyze --only army    # analyze specific stems
    .\run.ps1 analyze --print        # print BPM/key without writing metadata
    .\run.ps1 shell                  # drop into the venv Python REPL

  Anything after the command word is passed straight through to the script.
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('render', 'shorts', 'batch', 'metadata', 'analyze', 'gather', 'upload', 'shell')]
    [string]$Command = 'render',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

# --- Environment plumbing ---------------------------------------------------
# Refresh PATH so FFmpeg (installed via winget) is always found.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
# Force UTF-8 so the scripts' box-drawing output never crashes on Windows.
$env:PYTHONUTF8 = "1"

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "ERROR: venv not found at $Py" -ForegroundColor Red
    Write-Host "Create it with:  python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Quick FFmpeg sanity check
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: ffmpeg not on PATH. Install with:  winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

# --- Dispatch ---------------------------------------------------------------
switch ($Command) {
    'render'   { & $Py (Join-Path $Root 'render_lit.py')   @Rest }
    'shorts'   { & $Py (Join-Path $Root 'render_shorts.py') @Rest }
    'gather'   { & $Py (Join-Path $Root 'gather_beats.py') @Rest }
    'batch'    { & $Py (Join-Path $Root 'batch_ten.py')    @Rest }
    'metadata' { & $Py (Join-Path $Root 'seo_metadata.py') @Rest }
    'analyze'  { & $Py (Join-Path $Root 'beat_analysis.py') @Rest }
    'upload'   { & $Py (Join-Path $Root 'upload.py')       @Rest }
    'shell'    { & $Py @Rest }
}
exit $LASTEXITCODE
