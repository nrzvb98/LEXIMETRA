[CmdletBinding()]
param(
    [ValidateSet("x64")]
    [string]$TargetArch = $(if ($env:TARGET_ARCH) { $env:TARGET_ARCH } else { "x64" }),
    [string]$FFmpegVersion = $(if ($env:FFMPEG_VERSION) { $env:FFMPEG_VERSION } else { "8.0.1" }),
    [string]$VenvPython = $(if ($env:VENV_PYTHON) { $env:VENV_PYTHON } else { "" })
)

$ErrorActionPreference = "Stop"

$AppName = "HALA RT"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..\..")
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build\windows\$TargetArch"
$AppDir = Join-Path $DistDir $AppName
$Launcher = Join-Path $ScriptDir "hala_rt_launcher.py"
$IconPath = Join-Path $ScriptDir "icons\hala-rt-icon.ico"
$FFmpegPrefix = if ($env:FFMPEG_PREFIX) {
    $env:FFMPEG_PREFIX
} else {
    Join-Path $RootDir "build\ffmpeg\ffmpeg-$FFmpegVersion-windows-$TargetArch\install"
}

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    throw "This Windows build script must be run on Windows."
}

if (-not $VenvPython) {
    $VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Python virtualenv not found at $VenvPython. Create it and install the project first."
}

if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "Windows icon not found at $IconPath."
}

Push-Location $RootDir
try {
    & $VenvPython -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not installed in $VenvPython. Install it with: $VenvPython -m pip install pyinstaller"
    }

    $Version = & $VenvPython -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read project version from pyproject.toml."
    }

    $PythonMachine = (& $VenvPython -c 'import platform; print(platform.machine().lower())').Trim()
    if ($PythonMachine -notin @("amd64", "x86_64")) {
        throw "Windows packaging currently supports x64 Python only; this virtualenv reports $PythonMachine."
    }

    $ZipPath = Join-Path $DistDir "HALA_RT_${Version}_windows_$TargetArch.zip"
    Write-Host "Building $AppName $Version for Windows $TargetArch..."

    Remove-Item -Recurse -Force -LiteralPath $BuildDir, $AppDir, $ZipPath -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir | Out-Null
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir "pyinstaller_config"

    & $VenvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name $AppName `
        --icon $IconPath `
        --paths (Join-Path $RootDir "src") `
        --workpath (Join-Path $BuildDir "work") `
        --specpath (Join-Path $BuildDir "spec") `
        --distpath $DistDir `
        --collect-data "_soundfile_data" `
        --collect-binaries "_soundfile_data" `
        --collect-data "_sounddevice_data" `
        --collect-binaries "_sounddevice_data" `
        $Launcher
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    if (-not (Test-Path -LiteralPath $AppDir)) {
        throw "Expected app directory was not created: $AppDir"
    }

    if ($env:HALA_BUNDLE_FFMPEG -ne "0") {
        Write-Host "Building or reusing bundled FFmpeg $FFmpegVersion..."
        & (Join-Path $ScriptDir "build_ffmpeg.ps1") `
            -TargetArch $TargetArch `
            -FFmpegVersion $FFmpegVersion `
            -Prefix $FFmpegPrefix
        if ($LASTEXITCODE -ne 0) {
            throw "FFmpeg build failed."
        }

        $BundledBinDir = Join-Path $AppDir "_internal\bin"
        $BundledLicenseDir = Join-Path $AppDir "_internal\licenses"
        New-Item -ItemType Directory -Force -Path $BundledBinDir, $BundledLicenseDir | Out-Null

        Copy-Item -Force -LiteralPath (Join-Path $FFmpegPrefix "bin\ffmpeg.exe") -Destination (Join-Path $BundledBinDir "ffmpeg.exe")
        Copy-Item -Force -LiteralPath (Join-Path $FFmpegPrefix "bin\ffprobe.exe") -Destination (Join-Path $BundledBinDir "ffprobe.exe")
        Get-ChildItem -LiteralPath (Join-Path $FFmpegPrefix "bin") -Filter "*.dll" -ErrorAction SilentlyContinue |
            Copy-Item -Force -Destination $BundledBinDir

        $VersionOutput = & (Join-Path $BundledBinDir "ffmpeg.exe") -version
        if ($LASTEXITCODE -ne 0) {
            throw "Bundled ffmpeg.exe did not run."
        }
        if ($VersionOutput -match "--enable-(gpl|nonfree)") {
            throw "Bundled FFmpeg must not be configured with GPL or nonfree flags."
        }

        $LicenseSource = Join-Path $FFmpegPrefix "licenses\ffmpeg"
        $LicenseDest = Join-Path $BundledLicenseDir "ffmpeg"
        Remove-Item -Recurse -Force -LiteralPath $LicenseDest -ErrorAction SilentlyContinue
        Copy-Item -Recurse -Force -LiteralPath $LicenseSource -Destination $LicenseDest
    } else {
        Write-Host "Skipping bundled FFmpeg because HALA_BUNDLE_FFMPEG=0."
    }

    Write-Host "Creating distributable archive..."
    Compress-Archive -LiteralPath $AppDir -DestinationPath $ZipPath -Force

    Write-Host "Built app: $AppDir"
    Write-Host "Built archive: $ZipPath"
} finally {
    Pop-Location
}
