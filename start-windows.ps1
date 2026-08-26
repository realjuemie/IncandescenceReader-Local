$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Runtime not installed. Run setup-windows.ps1 first."
}

Set-Location -LiteralPath $projectDir
$port = if ($env:PORT) { $env:PORT } else { "8787" }
Write-Host "Local URL: http://127.0.0.1:$port"
$lanAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
    Select-Object -ExpandProperty IPAddress -Unique
foreach ($address in $lanAddresses) {
    Write-Host "LAN URL:   http://$address`:$port"
}
& $venvPython (Join-Path $projectDir "app.py")
