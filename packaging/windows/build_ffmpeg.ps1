[CmdletBinding()]
param(
    [ValidateSet("x64")]
    [string]$TargetArch = $(if ($env:TARGET_ARCH) { $env:TARGET_ARCH } else { "x64" }),
    [string]$FFmpegVersion = $(if ($env:FFMPEG_VERSION) { $env:FFMPEG_VERSION } else { "8.0.1" }),
    [string]$Prefix = $(if ($env:FFMPEG_PREFIX) { $env:FFMPEG_PREFIX } else { "" })
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..\..")
if (-not $Prefix) {
    $Prefix = Join-Path $RootDir "build\ffmpeg\ffmpeg-$FFmpegVersion-windows-$TargetArch\install"
}

$BuildRoot = Join-Path $RootDir "build\ffmpeg\ffmpeg-$FFmpegVersion-windows-$TargetArch"
$SourceUrl = "https://ffmpeg.org/releases/ffmpeg-$FFmpegVersion.tar.xz"
$SourceArchive = Join-Path $BuildRoot "ffmpeg-$FFmpegVersion.tar.xz"
$SourceDir = Join-Path $BuildRoot "src\ffmpeg-$FFmpegVersion"
$LicenseDir = Join-Path $Prefix "licenses\ffmpeg"

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    throw "This FFmpeg build script must be run on Windows."
}

function Get-PeMachine {
    param([string]$Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $reader = New-Object System.IO.BinaryReader($stream)
        $stream.Seek(0x3c, [System.IO.SeekOrigin]::Begin) | Out-Null
        $peOffset = $reader.ReadInt32()
        $stream.Seek($peOffset + 4, [System.IO.SeekOrigin]::Begin) | Out-Null
        return $reader.ReadUInt16()
    } finally {
        $stream.Dispose()
    }
}

function Assert-FfmpegBinary {
    param([string]$Binary)

    if (-not (Test-Path -LiteralPath $Binary)) {
        throw "Expected executable FFmpeg binary missing: $Binary"
    }

    $machine = Get-PeMachine -Path $Binary
    if ($machine -ne 0x8664) {
        throw "Expected $Binary to be an x64 PE binary, got machine type 0x$('{0:x4}' -f $machine)."
    }

    $versionOutput = & $Binary -version
    if ($LASTEXITCODE -ne 0) {
        throw "$Binary did not run."
    }
    if ($versionOutput -match "--enable-(gpl|nonfree)") {
        throw "Bundled FFmpeg must not be configured with GPL or nonfree flags."
    }
}

function Write-LicenseFiles {
    param([string]$FromSourceDir)

    New-Item -ItemType Directory -Force -Path $LicenseDir | Out-Null
    $copiedLicenseCount = 0
    foreach ($licenseName in @("LICENSE.md", "COPYING.LGPLv2.1", "COPYING.LGPLv3")) {
        $licensePath = Join-Path $FromSourceDir $licenseName
        if (Test-Path -LiteralPath $licensePath) {
            Copy-Item -Force -LiteralPath $licensePath -Destination $LicenseDir
            $copiedLicenseCount += 1
        }
    }
    if ($copiedLicenseCount -eq 0) {
        @(
            "# Supplied FFmpeg Binary",
            "",
            "No FFmpeg source license files were found next to the supplied binary directory.",
            "Before distributing this package, include the applicable FFmpeg license notices",
            "for the exact FFmpeg build placed in HALA_FFMPEG_DIR."
        ) | Out-File -Encoding utf8 -FilePath (Join-Path $LicenseDir "SUPPLIED_BINARY_NOTICE.md")
    }

    & (Join-Path $Prefix "bin\ffmpeg.exe") -version | Out-File -Encoding utf8 -FilePath (Join-Path $LicenseDir "ffmpeg-version.txt")
    @(
        "# Bundled FFmpeg",
        "",
        "HALA RT bundles FFmpeg $FFmpegVersion for local audio decoding in the packaged",
        "Windows app. This build is configured without GPL or nonfree flags.",
        "",
        "This notice is provided for engineering compliance hygiene and is not legal",
        "advice. See LICENSE.md and the LGPL license files in this directory."
    ) | Out-File -Encoding utf8 -FilePath (Join-Path $LicenseDir "README.md")
}

function Resolve-SuppliedFfmpegBinDir {
    param([string]$Directory)

    if (Test-Path -LiteralPath (Join-Path $Directory "ffmpeg.exe")) {
        return $Directory
    }

    $NestedBin = Join-Path $Directory "bin"
    if (Test-Path -LiteralPath (Join-Path $NestedBin "ffmpeg.exe")) {
        return $NestedBin
    }

    throw "HALA_FFMPEG_DIR must contain ffmpeg.exe and ffprobe.exe, directly or under a bin directory."
}

function Import-SuppliedFfmpeg {
    param([string]$Directory)

    $SuppliedBinDir = Resolve-SuppliedFfmpegBinDir -Directory $Directory
    if (-not (Test-Path -LiteralPath (Join-Path $SuppliedBinDir "ffprobe.exe"))) {
        throw "HALA_FFMPEG_DIR is missing ffprobe.exe."
    }

    $InstallBinDir = Join-Path $Prefix "bin"
    New-Item -ItemType Directory -Force -Path $InstallBinDir | Out-Null
    Copy-Item -Force -LiteralPath (Join-Path $SuppliedBinDir "ffmpeg.exe") -Destination (Join-Path $InstallBinDir "ffmpeg.exe")
    Copy-Item -Force -LiteralPath (Join-Path $SuppliedBinDir "ffprobe.exe") -Destination (Join-Path $InstallBinDir "ffprobe.exe")
    Get-ChildItem -LiteralPath $SuppliedBinDir -Filter "*.dll" -ErrorAction SilentlyContinue |
        Copy-Item -Force -Destination $InstallBinDir

    Assert-FfmpegBinary -Binary (Join-Path $InstallBinDir "ffmpeg.exe")
    Assert-FfmpegBinary -Binary (Join-Path $InstallBinDir "ffprobe.exe")

    $licenseSource = if ($env:HALA_FFMPEG_LICENSE_DIR) { $env:HALA_FFMPEG_LICENSE_DIR } else { Split-Path -Parent $SuppliedBinDir }
    Write-LicenseFiles -FromSourceDir $licenseSource
    Write-Host "Using supplied FFmpeg build: $Prefix"
}

function Get-MsysBash {
    if ($env:MSYS2_BASH -and (Test-Path -LiteralPath $env:MSYS2_BASH)) {
        return $env:MSYS2_BASH
    }

    $candidates = @(
        "C:\msys64\usr\bin\bash.exe",
        "C:\tools\msys64\usr\bin\bash.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "MSYS2 bash was not found. Install MSYS2 or set HALA_FFMPEG_DIR to a prepared LGPL FFmpeg directory."
}

function Convert-ToMsysPath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.Contains("'")) {
        throw "Paths containing single quotes are not supported by this build script."
    }
    if ($fullPath.Length -lt 3 -or $fullPath[1] -ne ":") {
        throw "Only local drive paths are supported for the MSYS2 FFmpeg build: $fullPath"
    }

    $drive = [char]::ToLowerInvariant($fullPath[0])
    $rest = $fullPath.Substring(2).Replace("\", "/")
    return "/$drive$rest"
}

function Quote-Msys {
    param([string]$Value)

    if ($Value.Contains("'")) {
        throw "Paths containing single quotes are not supported by this build script."
    }
    return "'$Value'"
}

if ($env:HALA_REBUILD_FFMPEG -eq "1") {
    Remove-Item -Recurse -Force -LiteralPath $BuildRoot -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $Prefix | Out-Null

$ExistingFfmpeg = Join-Path $Prefix "bin\ffmpeg.exe"
$ExistingFfprobe = Join-Path $Prefix "bin\ffprobe.exe"
if ((Test-Path -LiteralPath $ExistingFfmpeg) -and (Test-Path -LiteralPath $ExistingFfprobe)) {
    Assert-FfmpegBinary -Binary $ExistingFfmpeg
    Assert-FfmpegBinary -Binary $ExistingFfprobe
    if (Test-Path -LiteralPath $SourceDir) {
        Write-LicenseFiles -FromSourceDir $SourceDir
    }
    Write-Host "Using existing FFmpeg build: $Prefix"
    exit 0
}

if ($env:HALA_FFMPEG_DIR) {
    Import-SuppliedFfmpeg -Directory $env:HALA_FFMPEG_DIR
    exit 0
}

$MsysBash = Get-MsysBash

if (-not (Test-Path -LiteralPath $SourceArchive)) {
    Write-Host "Downloading FFmpeg $FFmpegVersion source..."
    Invoke-WebRequest -Uri $SourceUrl -OutFile $SourceArchive
}

if (-not (Test-Path -LiteralPath $SourceDir)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $BuildRoot "src") | Out-Null
    tar -xJf $SourceArchive -C (Join-Path $BuildRoot "src")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not extract FFmpeg source archive."
    }
}

$SourceDirMsys = Convert-ToMsysPath -Path $SourceDir
$PrefixMsys = Convert-ToMsysPath -Path $Prefix
$Jobs = [Math]::Max(1, [Environment]::ProcessorCount)
$ConfigureFlags = @(
    "--prefix=$PrefixMsys",
    "--arch=x86_64",
    "--target-os=mingw32",
    "--cc=gcc",
    "--enable-static",
    "--disable-shared",
    "--disable-autodetect",
    "--disable-network",
    "--disable-doc",
    "--disable-debug",
    "--disable-ffplay",
    "--disable-devices",
    "--disable-avdevice",
    "--disable-x86asm",
    "--extra-ldflags=-static",
    "--pkg-config=false"
)

$QuotedConfigureFlags = $ConfigureFlags | ForEach-Object { Quote-Msys $_ }
$ConfigureCommand = "./configure $($QuotedConfigureFlags -join ' ')"
$BuildCommand = @(
    "set -e",
    "export MSYSTEM=MINGW64",
    "export CHERE_INVOKING=1",
    "export PATH=/mingw64/bin:/usr/bin:`$PATH",
    "cd $(Quote-Msys $SourceDirMsys)",
    "export PKG_CONFIG=false",
    $ConfigureCommand,
    "if grep -E -- '--enable-(gpl|nonfree)' config.h ffbuild/config.log >/dev/null 2>&1; then echo 'GPL or nonfree flag detected' >&2; exit 1; fi",
    "make -j $Jobs",
    "make install"
) -join "; "

Write-Host "Configuring and building FFmpeg $FFmpegVersion with MSYS2..."
& $MsysBash -lc $BuildCommand
if ($LASTEXITCODE -ne 0) {
    throw "FFmpeg build failed."
}

Assert-FfmpegBinary -Binary $ExistingFfmpeg
Assert-FfmpegBinary -Binary $ExistingFfprobe
Write-LicenseFiles -FromSourceDir $SourceDir

Write-Host "Built FFmpeg: $Prefix"
