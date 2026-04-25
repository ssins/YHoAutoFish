param(
    [switch]$Plain,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = "YHoAutoFish"
$ReleaseDir = Join-Path $ProjectRoot "release"
$ZipPath = Join-Path $ReleaseDir "$AppName-windows.zip"

Set-Location $ProjectRoot

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if (-not $SkipInstall) {
    Invoke-Checked "python" @("-m", "pip", "install", "-r", "requirements-build.txt")
}

Invoke-Checked "python" @("tools\make_icon.py")

if ($Plain) {
    Invoke-Checked "python" @("-m", "PyInstaller", "--clean", "--noconfirm", ".\YHoAutoFish.spec")
} else {
    Invoke-Checked "pyarmor" @("gen", "-O", ".\build_obf", "-r", ".\main.py", ".\core")
    Invoke-Checked "python" @("-m", "PyInstaller", "--clean", "--noconfirm", ".\YHoAutoFish.obf.spec")
}

$CandidateDirs = @(
    (Join-Path $ProjectRoot "dist\$AppName"),
    (Join-Path $ProjectRoot ".pyarmor\pack\dist\$AppName")
)

$DistDir = $null
foreach ($Candidate in $CandidateDirs) {
    if (Test-Path (Join-Path $Candidate "$AppName.exe")) {
        $DistDir = $Candidate
        break
    }
}

if (-not $DistDir) {
    throw "Build finished, but $AppName.exe was not found in expected dist directories."
}

$BundledRecords = Join-Path $DistDir "records.json"
if (Test-Path -LiteralPath $BundledRecords) {
    Remove-Item -LiteralPath $BundledRecords -Force
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force

Write-Host "EXE: $(Join-Path $DistDir "$AppName.exe")"
Write-Host "ZIP: $ZipPath"
