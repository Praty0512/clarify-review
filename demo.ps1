# ClarifyReview - the demo, in the order it makes sense to a reviewer.
# PowerShell 5.1 equivalent of demo.sh. Saved as UTF-8 with BOM (the headers use
# box-drawing characters, which PS 5.1 only reads correctly with a BOM).
#
#   powershell -ExecutionPolicy Bypass -File .\demo.ps1          Stages 1-2 live, 3-4 replayed offline.
#   powershell -ExecutionPolicy Bypass -File .\demo.ps1 -Full    Live Stages 3-4. Needs GEMINI_API_KEY.
#   powershell -ExecutionPolicy Bypass -File .\demo.ps1 -Step    Pause for Enter between sections.
param([switch]$Full, [switch]$Step)
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

# Auto-detect the venv layout (Windows: .venv\Scripts, macOS/Linux with pwsh: .venv/bin).
$CR = $env:CR; $PY = $env:PY
if (-not $CR) { foreach ($c in '.venv\Scripts\clarifyreview.exe', '.venv/bin/clarifyreview') { if (Test-Path -LiteralPath $c) { $CR = $c; break } } }
if (-not $PY) { foreach ($c in '.venv\Scripts\python.exe', '.venv/bin/python') { if (Test-Path -LiteralPath $c) { $PY = $c; break } } }
if (-not $CR -or -not $PY) {
    [Console]::Error.WriteLine('No virtualenv found. Set it up first: python -m venv .venv; .venv\Scripts\pip install -e .')
    exit 1
}

# Make child Python processes and our own output UTF-8 so box-drawing characters survive pipes.
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$script:Sections = 0
function Pause-Section {
    $script:Sections++
    if ($Step -and $script:Sections -gt 1) { Write-Host ''; [void](Read-Host '[press Enter to continue]') }
}
function hr($t) { Pause-Section; Write-Host ''; Write-Host ([string][char]0x2500 * 2 + " $t " + [string][char]0x2500 * 38) -ForegroundColor Blue }
function say($t) { Write-Host $t -ForegroundColor DarkGray }
function cmd($label, [scriptblock]$sb) {
    Write-Host "`$ $label" -ForegroundColor Yellow
    Write-Host ''
    & $sb
}
function Out-Lines { process { "$_" } }   # flatten stderr ErrorRecords to plain text

function Test-GeminiKey {
    if ($env:GEMINI_API_KEY) { return $true }
    if (Test-Path -LiteralPath .env) {
        foreach ($line in Get-Content -LiteralPath .env) {
            if ($line -match '^\s*(export\s+)?GEMINI_API_KEY\s*=\s*["'']?[^"''\s#]') { return $true }
        }
    }
    return $false
}

hr '1. The problem: an ambiguous pull request'
say 'A null check disappears. Commit message: "fix". No linked issue.'
say 'A single-pass reviewer must guess what this change was for.'
Write-Host ''; Get-Content -LiteralPath examples\ambiguous.diff -Encoding UTF8

hr '2. Stage 1 - what the system understands about the diff'
say "Not 'lines 10-15 changed', but which SYMBOL changed. Note the stable"
say 'fingerprint: ingestion is deterministic, which the ablation depends on.'
cmd "clarifyreview ingest --diff examples/ambiguous.diff --title 'fix login bug' --commit-msg 'fix' 2>&1 | Select-Object -First 20" {
    & $CR ingest --diff examples/ambiguous.diff --title 'fix login bug' --commit-msg 'fix' 2>&1 | Out-Lines | Select-Object -First 20
}

hr '3. Stage 2 - the contribution: ask, or proceed?'
cmd 'clarifyreview detect --diff examples/ambiguous.diff --commit-msg fix --features' {
    & $CR detect --diff examples/ambiguous.diff --commit-msg 'fix' --features 2>&1 | Out-Lines
}

hr '4. The other half: knowing when to stay quiet'
say 'Same detector, a well-described PR with a regression test in the same diff.'
say 'A tool that asks on every PR is unusable, so this case matters as much.'
Write-Host ''; Get-Content -LiteralPath examples\clear.diff -Encoding UTF8
cmd 'clarifyreview detect --diff examples/clear.diff --commit-msg <well-described message>' {
    & $CR detect --diff examples/clear.diff --commit-msg 'Trim surrounding whitespace before slugifying so pasted CMS titles do not produce trailing dashes' 2>&1 | Out-Lines
}

$live = $Full
if ($Full -and -not (Test-GeminiKey)) {
    say '-Full needs GEMINI_API_KEY (not set in the environment or .env); falling back to the offline replay.'
    $live = $false
}
if ($live) {
    hr '5. Stages 3 and 4 - the full pipeline'
    say 'Generates a clarifying question, then reviews. Needs GEMINI_API_KEY.'
    cmd 'clarifyreview review --diff examples/ambiguous.diff --pr-id demo' {
        & $CR review --diff examples/ambiguous.diff --pr-id demo 2>&1 | Out-Lines
    }
} else {
    hr '5. Stages 3 and 4 - a recorded run from the study, replayed offline'
    say 'The same pull request reviewed three ways. Without its issue text the'
    say 'reviewer misreads it; ClarifyReview asks, gets an answer, and matches the'
    say "full-context review. ('.\demo.ps1 -Full' runs Stages 3-4 live instead.)"
    cmd 'clarifyreview replay --db data/study_v2.db' {
        & $CR replay --db data/study_v2.db 2>&1 | Out-Lines
    }
}

hr '6. The evidence underneath'
cmd 'python -m pytest -q 2>&1 | Select-Object -Last 3' {
    & $PY -m pytest -q 2>&1 | Out-Lines | Select-Object -Last 3
}
Write-Host ''
exit 0
