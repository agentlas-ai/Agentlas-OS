# Agentlas Desktop - one-line install for Windows.
#
# Paste into Windows PowerShell:
#   irm https://agentlas.cloud/install.ps1 | iex
#   $env:AGENTLAS_WITH_ENGINE="1"; irm https://agentlas.cloud/install.ps1 | iex
#
# agentlas.cloud/install.ps1 redirects to this file in the public Agentlas-OS repo.
# Options: -WithEngine / -NoOpen, or env AGENTLAS_WITH_ENGINE=1 / AGENTLAS_NO_OPEN=1
# (irm | iex cannot pass parameters, so the environment variables are the main form).
#
# What it does, in order:
#   1. Reads latest.yml from github.com/agentlas-ai/agentlas-desktop-releases.
#   2. Downloads the Windows installer and checks its sha512 against that metadata.
#      A mismatch stops the install; nothing is run.
#   3. Runs the installer silently for the current user (no administrator prompt).
#   4. -WithEngine also installs Agentlas OS into your agent hosts through Git Bash
#      (scripts/install-all-runtimes.sh). Without Git Bash it tells you how to add it.
param(
  [switch]$WithEngine,
  [switch]$NoOpen
)
$ErrorActionPreference = "Stop"
if ($env:AGENTLAS_WITH_ENGINE -eq "1") { $WithEngine = $true }
if ($env:AGENTLAS_NO_OPEN -eq "1") { $NoOpen = $true }
$ProgressPreference = "SilentlyContinue"

$releases = if ($env:AGENTLAS_DESKTOP_RELEASES) { $env:AGENTLAS_DESKTOP_RELEASES } else { "agentlas-ai/agentlas-desktop-releases" }
$engineUrl = "https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh"
$base = "https://github.com/$releases/releases/latest/download"

function Say([string]$message) { Write-Host "==> $message" }
function Stop-Install([string]$message) { Write-Host "Agentlas Desktop install stopped: $message" -ForegroundColor Red; exit 1 }

if (-not [Environment]::Is64BitOperatingSystem) { Stop-Install "Agentlas Desktop needs 64-bit Windows." }

$work = Join-Path ([IO.Path]::GetTempPath()) ("agentlas-desktop-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  Say "Reading the latest Agentlas Desktop release"
  $meta = (Invoke-WebRequest -UseBasicParsing "$base/latest.yml").Content
  $version = ([regex]::Match($meta, '(?m)^version:\s*(\S+)')).Groups[1].Value
  $entry = [regex]::Match($meta, '(?ms)-\s*url:\s*(\S*Setup\.exe)\s*\r?\n\s*sha512:\s*(\S+)')
  if (-not $entry.Success) { Stop-Install "no Windows installer in latest.yml." }
  $asset = $entry.Groups[1].Value
  $expected = $entry.Groups[2].Value

  Say "Downloading Agentlas Desktop $version ($asset)"
  $installer = Join-Path $work $asset
  Invoke-WebRequest -UseBasicParsing "$base/$asset" -OutFile $installer

  # electron-builder publishes sha512 as base64 of the raw digest.
  $stream = [IO.File]::OpenRead($installer)
  try { $actual = [Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash($stream)) } finally { $stream.Dispose() }
  if ($actual -ne $expected) { Stop-Install "checksum mismatch for $asset - the installer was not run." }
  Say "Checksum verified (sha512)"

  Say "Installing"
  $process = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
  if ($process.ExitCode -ne 0) { Stop-Install "the installer exited with code $($process.ExitCode)." }
  Say "Installed Agentlas Desktop $version"

  if (-not $NoOpen) {
    $exe = Join-Path $env:LOCALAPPDATA "Programs\Agentlas\Agentlas.exe"
    if (Test-Path $exe) { Start-Process $exe | Out-Null }
  }

  if ($WithEngine) {
    $bash = @(
      (Join-Path $env:ProgramFiles "Git\bin\bash.exe"),
      (Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe"),
      (Join-Path $env:LOCALAPPDATA "Programs\Git\bin\bash.exe")
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $bash) {
      Write-Host "Agentlas OS needs Git Bash on Windows. Install Git for Windows from https://git-scm.com/download/win, then run in Git Bash:" -ForegroundColor Yellow
      Write-Host "  curl -fsSL $engineUrl | bash"
    } else {
      Say "Installing Agentlas OS into your agent hosts (Git Bash)"
      & $bash -lc "curl -fsSL $engineUrl | bash"
      if ($LASTEXITCODE -ne 0) { Stop-Install "Agentlas OS install failed (exit $LASTEXITCODE)." }
    }
  }
  Say "Done. Agentlas Desktop $version is ready."
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
