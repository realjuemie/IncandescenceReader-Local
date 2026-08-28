$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$venvDir = Join-Path $projectDir ".venv"
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue

if ($pythonLauncher) {
    & $pythonLauncher.Source -3 -m venv $venvDir
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Install Python 3.10 or newer and enable Add Python to PATH."
    }
    & $pythonCommand.Source -m venv $venvDir
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectDir "requirements.txt")

$firewallRuleName = "Incandescence Reader (TCP 8787)"
$windowsIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$windowsPrincipal = [Security.Principal.WindowsPrincipal]::new($windowsIdentity)
$isAdministrator = $windowsPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdministrator -and (Get-Command New-NetFirewallRule -ErrorAction SilentlyContinue)) {
    $existingRule = Get-NetFirewallRule -DisplayName $firewallRuleName -ErrorAction SilentlyContinue
    if (-not $existingRule) {
        New-NetFirewallRule `
            -DisplayName $firewallRuleName `
            -Description "Allow Incandescence Reader from the local subnet only." `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort 8787 `
            -Profile Private,Public `
            -RemoteAddress LocalSubnet | Out-Null
    }
    Write-Host "Local-network firewall rule is ready for TCP 8787." -ForegroundColor Green
} else {
    Write-Warning "Run setup-windows.ps1 as Administrator once if other LAN devices cannot open TCP 8787."
}

Write-Host ""
Write-Host "Setup complete. Double-click start-windows.cmd to launch the reader." -ForegroundColor Green
