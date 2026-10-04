# Builds release/DiscordSoundBot-win64.zip: the app folder with DiscordSoundBot.exe,
# a bundled ffmpeg (LGPL build) and docs. Works in Windows PowerShell 5.1 and pwsh.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with a progress bar

$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root 'build'
$appDir = Join-Path $build 'dist\DiscordSoundBot'
$release = Join-Path $root 'release'
Set-Location $root

# Separate venv so a running copy of the bot doesn't lock files in .venv.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $build 'venv'
uv sync --locked --no-editable
if ($LASTEXITCODE) { throw 'uv sync failed' }

uv run --no-sync pyinstaller --noconfirm --clean --windowed `
    --name DiscordSoundBot `
    --icon "$root\assets\icon.ico" `
    --add-data "$root\assets\icon.ico;assets" `
    --copy-metadata discord-sound-bot `
    --collect-all discord `
    --collect-all davey `
    --collect-all nacl `
    --hidden-import _cffi_backend `
    --distpath "$build\dist" --workpath "$build\work" --specpath $build `
    "$root\packaging\launcher.py"
if ($LASTEXITCODE) { throw 'pyinstaller failed' }

$check = Start-Process "$appDir\DiscordSoundBot.exe" -ArgumentList '--self-check' -Wait -PassThru
if ($check.ExitCode) { throw "Self-check failed: voice dependencies missing (exit $($check.ExitCode))" }

# Latest stable LGPL static ffmpeg from BtbN/FFmpeg-Builds.
$ffZip = Join-Path $build 'ffmpeg.zip'
if (-not (Test-Path $ffZip)) {
    $assets = (Invoke-RestMethod 'https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest').assets
    $asset = $assets |
        Where-Object { $_.name -match '^ffmpeg-n[\d.]+-latest-win64-lgpl-[\d.]+\.zip$' } |
        Sort-Object { [version]($_.name -replace '^.*-lgpl-([\d.]+)\.zip$', '$1') } |
        Select-Object -Last 1
    Write-Host "Downloading $($asset.name)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $ffZip
}
$ffDir = Join-Path $build 'ffmpeg'
if (Test-Path $ffDir) { Remove-Item $ffDir -Recurse -Force }
Expand-Archive $ffZip -DestinationPath $ffDir
$ffRoot = (Get-ChildItem $ffDir -Directory | Select-Object -First 1).FullName
Copy-Item "$ffRoot\bin\ffmpeg.exe" $appDir
Copy-Item "$ffRoot\LICENSE.txt" "$appDir\FFMPEG-LICENSE.txt"

Copy-Item "$root\README.md" $appDir
Copy-Item "$root\LICENSE" "$appDir\LICENSE.txt"
New-Item -ItemType Directory -Force "$appDir\sounds" | Out-Null

New-Item -ItemType Directory -Force $release | Out-Null
$zip = Join-Path $release 'DiscordSoundBot-win64.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $appDir -DestinationPath $zip
Write-Host "Built $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
