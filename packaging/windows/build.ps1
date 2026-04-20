Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$vendorBinDir = Join-Path $repoRoot "vendor\windows\bin"
$requiredBinaries = @("ffmpeg.exe", "ffprobe.exe")

foreach ($binary in $requiredBinaries) {
    $candidate = Join-Path $vendorBinDir $binary
    if (-not (Test-Path $candidate)) {
        throw "Missing $binary in $vendorBinDir. Add both ffmpeg.exe and ffprobe.exe before building."
    }
}

Push-Location $repoRoot
try {
    py -m pip install -r requirements.txt
    py -m pip install pyinstaller

    if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path ".\web\package.json")) {
        Push-Location ".\web"
        try {
            npm run build
        }
        finally {
            Pop-Location
        }
    }

    Remove-Item ".\build" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item ".\dist" -Recurse -Force -ErrorAction SilentlyContinue

    py -m PyInstaller ".\packaging\windows\video_downloader.spec" --noconfirm --clean

    Write-Host ""
    Write-Host "Build complete:"
    Write-Host "  $repoRoot\dist\VideoDownloader\VideoDownloader.exe"
    Write-Host ""
    Write-Host "Send the entire dist\VideoDownloader folder to the Windows machine."
}
finally {
    Pop-Location
}
