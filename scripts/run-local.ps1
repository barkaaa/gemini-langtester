param(
    [int]$Port = 8000,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

function Test-PortAvailable {
    param(
        [string]$Address,
        [int]$Port
    )

    $listener = $null
    try {
        $ip = [System.Net.IPAddress]::Parse($Address)
        $listener = [System.Net.Sockets.TcpListener]::new($ip, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Get-AvailablePort {
    param(
        [string]$Address,
        [int]$StartPort
    )

    for ($candidate = $StartPort; $candidate -lt ($StartPort + 50); $candidate++) {
        if (Test-PortAvailable -Address $Address -Port $candidate) {
            return $candidate
        }
    }

    throw "No available port found from $StartPort to $($StartPort + 49)."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$EnvFile = Join-Path $ProjectRoot ".env"
$ExampleEnvFile = Join-Path $ProjectRoot ".env.example"

Set-Location $ProjectRoot

$VersionText = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$VersionText -lt [version]"3.11") {
    throw "Python 3.11 or newer is required. Current version: $VersionText"
}

if (-not (Test-Path $EnvFile) -and (Test-Path $ExampleEnvFile)) {
    Copy-Item $ExampleEnvFile $EnvFile
    Write-Host "Created .env from .env.example. Check GEMINI_API_KEY before starting." -ForegroundColor Yellow
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    $Python = $VenvPython
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $Python -m pip install -r requirements.txt

$RequestedPort = $Port
$Port = Get-AvailablePort -Address $HostName -StartPort $Port
if ($Port -ne $RequestedPort) {
    Write-Host "Port $RequestedPort is unavailable. Using port $Port instead." -ForegroundColor Yellow
}

Write-Host "Starting app at http://$HostName`:$Port" -ForegroundColor Green
& $Python -m uvicorn main:app --host $HostName --port $Port --reload
