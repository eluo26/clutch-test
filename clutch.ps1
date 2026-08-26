<#
.SYNOPSIS
  Clutch task runner for Windows. The PowerShell equivalent of the Makefile.

.DESCRIPTION
  Run from the repository root:

      .\clutch.ps1 setup      # create a virtualenv, install backend + frontend
      .\clutch.ps1 seed       # load the bundled sample games
      .\clutch.ps1 api        # start the backend on http://localhost:8000
      .\clutch.ps1 web        # start the frontend on http://localhost:5173
      .\clutch.ps1 test       # run the Python test suite
      .\clutch.ps1 backtest   # print a calibration report
      .\clutch.ps1 ingest     # pull real NBA games via nba_api

  `api` and `web` each occupy a terminal, so run them in two windows. Open
  http://localhost:5173 once both are up.

.NOTES
  If PowerShell refuses to run this file ("running scripts is disabled on this
  system"), allow local scripts for your user once:

      Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

  That permits local scripts you wrote while still blocking unsigned ones from
  the internet. Alternatively, run this file without changing anything:

      powershell -ExecutionPolicy Bypass -File .\clutch.ps1 setup
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'setup', 'seed', 'api', 'web', 'test', 'lint', 'backtest', 'fixtures', 'ingest', 'clean')]
    [string]$Command = 'help',

    [string]$Season = '2023-24',
    [int]$Limit = 25,
    [string]$Model = 'blend'
)

# Deliberately NOT 'Stop'. Under Windows PowerShell 5.1, a native command that
# writes anything to stderr — which npm and pip both do routinely, for progress
# and warnings — can surface as a terminating NativeCommandError. Every native
# call below checks $LASTEXITCODE explicitly instead, which is accurate rather
# than merely noisy.
$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'

function Write-Step($text) { Write-Host "`n=> $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "   $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "   $text" -ForegroundColor Yellow }

function Get-Python {
    <# Prefer the project virtualenv; fall back to whatever is on PATH. #>
    if (Test-Path $VenvPython) { return $VenvPython }

    foreach ($candidate in @('python', 'python3', 'py')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    throw "Python was not found. Install Python 3.11 or newer from https://python.org (tick 'Add python.exe to PATH' during setup), then reopen this terminal."
}

function Assert-Node {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found. Install Node.js 20 or newer from https://nodejs.org, then reopen this terminal."
    }
}

function Invoke-Setup {
    Write-Step 'Creating the virtual environment'
    if (Test-Path $VenvPython) {
        Write-Ok 'Already exists, reusing it.'
    }
    else {
        $py = Get-Python
        & $py -m venv (Join-Path $Root '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
        Write-Ok 'Created .venv'
    }

    Write-Step 'Installing backend dependencies (this takes a minute)'
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -e "$Backend[dev,llm]"
    if ($LASTEXITCODE -ne 0) { throw 'Backend install failed.' }
    Write-Ok 'Backend ready.'

    Write-Step 'Installing frontend dependencies'
    Assert-Node
    Push-Location $Frontend
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    }
    finally { Pop-Location }
    Write-Ok 'Frontend ready.'

    Write-Host "`nNext:  .\clutch.ps1 seed   then   .\clutch.ps1 api" -ForegroundColor White
}

function Invoke-Backend($moduleArgs) {
    $py = Get-Python
    if ($py -ne $VenvPython) {
        Write-Warn 'Using the system Python — run ".\clutch.ps1 setup" first for an isolated environment.'
    }
    Push-Location $Backend
    try {
        & $py @moduleArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally { Pop-Location }
}

switch ($Command) {
    'help' {
        Write-Host @"
Clutch — NBA analytics platform

  .\clutch.ps1 setup       create .venv, install backend + frontend deps
  .\clutch.ps1 seed        load the bundled sample games into SQLite
  .\clutch.ps1 api         run the backend    -> http://localhost:8000
  .\clutch.ps1 web         run the frontend   -> http://localhost:5173
  .\clutch.ps1 test        run the Python test suite
  .\clutch.ps1 lint        ruff check the backend
  .\clutch.ps1 backtest    print a calibration report  [-Model blend|brownian|markov]
  .\clutch.ps1 fixtures    regenerate the bundled sample data
  .\clutch.ps1 ingest      pull real games  [-Season 2023-24] [-Limit 25]
  .\clutch.ps1 clean       delete the local database and build output

First run:
  .\clutch.ps1 setup
  .\clutch.ps1 seed
  .\clutch.ps1 api          <- leave this running
  .\clutch.ps1 web          <- in a second terminal, then open localhost:5173
"@ -ForegroundColor White
    }

    'setup' { Invoke-Setup }

    'seed' {
        Write-Step 'Loading sample games'
        Invoke-Backend @('-m', 'app.ingest.cli', 'seed')
    }

    'api' {
        Write-Step 'Backend on http://localhost:8000  (Ctrl+C to stop)'
        Write-Host '   API docs: http://localhost:8000/docs' -ForegroundColor DarkGray
        Invoke-Backend @('-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000')
    }

    'web' {
        Write-Step 'Frontend on http://localhost:5173  (Ctrl+C to stop)'
        Assert-Node
        Push-Location $Frontend
        try { npm run dev } finally { Pop-Location }
    }

    'test' {
        Write-Step 'Running tests'
        Invoke-Backend @('-m', 'pytest')
    }

    'lint' {
        Write-Step 'Linting'
        Invoke-Backend @('-m', 'ruff', 'check', 'app', 'tests')
    }

    'backtest' {
        Write-Step "Backtesting the '$Model' model"
        Invoke-Backend @('-m', 'app.ingest.cli', 'backtest', '--model', $Model)
    }

    'fixtures' {
        Write-Step 'Regenerating sample fixtures'
        Invoke-Backend @('scripts/make_fixtures.py')
    }

    'ingest' {
        Write-Step "Ingesting real games: season $Season, up to $Limit games"
        Write-Warn 'stats.nba.com is rate limited — expect roughly one second per game.'
        $py = Get-Python
        & $py -m pip install -e "$Backend[ingest]" --quiet
        Invoke-Backend @('-m', 'app.ingest.cli', 'nba', '--season', $Season, '--limit', "$Limit")
    }

    'clean' {
        Write-Step 'Cleaning'
        Get-ChildItem -Path $Backend -Filter 'clutch.db*' -ErrorAction SilentlyContinue |
            Remove-Item -Force
        foreach ($dir in @((Join-Path $Frontend 'dist'), (Join-Path $Root 'java-sim\target'))) {
            if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
        }
        Get-ChildItem -Path $Root -Filter '__pycache__' -Recurse -Directory -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
        Write-Ok 'Done.'
    }
}
