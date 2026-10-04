[CmdletBinding()]
param(
    [ValidateSet('auto', 'cuda', 'cpu')][string]$Device = 'auto',
    [ValidateSet('qwen', 'sensevoice', 'paraformer', 'all')][string[]]$Models = @('qwen'),
    [switch]$SkipModels,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed with exit code $LASTEXITCODE" }
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'The desktop application currently supports Windows only.' }
    foreach ($tool in @('node.exe', 'pnpm.cmd', 'cargo.exe')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "$tool is missing. Install the prerequisites listed in README.md, then reopen your terminal."
        }
    }
    $nodeMajor = [int]((& node.exe --version).TrimStart('v').Split('.')[0])
    if ($nodeMajor -notin @(22, 24)) { throw 'Use Node.js 22 or 24; Node.js 24 is the verified version.' }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere) -or
        -not (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath)) {
        throw 'Install Microsoft C++ Build Tools with Desktop development with C++ (including Windows SDK).'
    }
    $python = $env:FTL_VOICE_PROMPT_PYTHON
    if (-not $python) {
        foreach ($relative in @('.venv\Scripts\python.exe', '.venv\python.exe')) {
            $candidate = Join-Path $projectRoot $relative
            if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
        }
    }
    Push-Location $projectRoot
    try {
        if ($CheckOnly) {
            if (-not $python) { throw 'Project Python is missing. Run setup without -CheckOnly to create it.' }
        } elseif (-not $python) {
            if (Test-Path -LiteralPath '.venv') { throw 'An incomplete .venv already exists; it will not be overwritten. Select a working Python with FTL_VOICE_PROMPT_PYTHON.' }
            Invoke-Checked 'py.exe' @('-3.12', '-m', 'venv', '.venv')
            $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
        }
        Invoke-Checked $python @('-c', 'import sys; assert sys.version_info[:2] == (3, 12), "Use Python 3.12 for the pinned environment"')
        if (-not $CheckOnly) {
            Invoke-Checked 'pnpm.cmd' @('install', '--frozen-lockfile')
            $useCuda = $Device -eq 'cuda' -or ($Device -eq 'auto' -and (Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue))
            $torchChannel = if ($useCuda) { 'cu128' } else { 'cpu' }
            Write-Host "Installing PyTorch 2.8.0 ($torchChannel). NVIDIA drivers must be installed separately."
            Invoke-Checked $python @('-m', 'pip', 'install', "torch==2.8.0+$torchChannel", "torchaudio==2.8.0+$torchChannel", '--index-url', "https://download.pytorch.org/whl/$torchChannel")
            Invoke-Checked $python @('-m', 'pip', 'install', '-c', 'backend/constraints.txt', '-e', 'backend[test]')
            Invoke-Checked $python @('-m', 'pip', 'check')
        }
        Push-Location (Join-Path $projectRoot 'backend')
        try {
            $doctorArgs = @('-m', 'voice_prompt_sidecar.manage', 'doctor', '--runtime')
            if ($Device -eq 'cuda') { $doctorArgs += '--require-cuda' }
            Invoke-Checked $python $doctorArgs
            if (-not $CheckOnly -and -not $SkipModels) {
                Write-Host 'Downloading official model weights. Their own licenses apply; see THIRD_PARTY_NOTICES.md.'
                Invoke-Checked $python (@('-m', 'voice_prompt_sidecar.manage', 'download', '--models') + $Models)
            }
        } finally { Pop-Location }
        Write-Host 'Environment checked. In VS Code select FTL Voice Prompt (quick start), then press F5.'
    } finally { Pop-Location }
} catch { Write-Error $_; exit 1 }
