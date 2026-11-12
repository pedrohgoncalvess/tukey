# Install Tukey for the current user on Windows (PowerShell 5.1 or newer).
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$Source = 'https://github.com/pedrohgoncalvess/tukey/archive/refs/heads/main.zip'
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Use install.sh on Linux or macOS.'
}

function Invoke-Uv {
    & $script:UvPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "uv failed with exit code $LASTEXITCODE."
    }
}

$uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
$uvDirectory = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else { Join-Path $HOME '.local\bin' }
$uvCandidate = Join-Path $uvDirectory 'uv.exe'
$legacyCandidate = Join-Path $HOME '.cargo\bin\uv.exe'

if ($uvCommand) {
    $script:UvPath = $uvCommand.Source
} elseif (Test-Path -LiteralPath $uvCandidate -PathType Leaf) {
    $script:UvPath = $uvCandidate
} elseif (Test-Path -LiteralPath $legacyCandidate -PathType Leaf) {
    $script:UvPath = $legacyCandidate
} else {
    Write-Host 'Installing uv from astral.sh...'
    $installer = Join-Path ([IO.Path]::GetTempPath()) ("tukey-uv-{0}.ps1" -f [guid]::NewGuid())
    $previousInstallDir = $env:UV_INSTALL_DIR
    $previousNoModifyPath = $env:UV_NO_MODIFY_PATH
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer -UseBasicParsing
        $env:UV_INSTALL_DIR = $uvDirectory
        $env:UV_NO_MODIFY_PATH = '1'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw "uv installation failed with exit code $LASTEXITCODE." }
    } finally {
        $env:UV_INSTALL_DIR = $previousInstallDir
        $env:UV_NO_MODIFY_PATH = $previousNoModifyPath
        if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force }
    }
    if (-not (Test-Path -LiteralPath $uvCandidate -PathType Leaf)) {
        throw "uv was not found at $uvCandidate after installation."
    }
    $script:UvPath = $uvCandidate
}

Write-Host "Installing Tukey from $Source..."
Invoke-Uv tool install --reinstall --python 3.12 $Source
$binDirectory = (Invoke-Uv tool dir --bin | Out-String).Trim()
Invoke-Uv tool update-shell

# Make the command available in this PowerShell session as well.
$pathEntries = $env:Path -split ';'
if ($pathEntries -notcontains $binDirectory) {
    $env:Path = "$binDirectory;$env:Path"
}
& (Join-Path $binDirectory 'tukey.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Tukey was installed but its version check failed.' }
Write-Host "`nTukey is installed in $binDirectory."
Write-Host 'Run: tukey --help'
Write-Host 'Open a new terminal in other applications to load the updated PATH.'
