[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $WindowsDir "..\..")).Path
$Spec = Join-Path $WindowsDir "artanimate.spec"
$Dist = Join-Path $ProjectRoot "dist"
$Work = Join-Path $ProjectRoot "build\windows"
$Executable = Join-Path $Dist "ArtAnimate.exe"
$SelfTestReport = Join-Path $Dist "ArtAnimate-self-test.json"
$BuildReport = Join-Path $Dist "ArtAnimate-build.json"
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$OriginalPath = $env:Path
$PythonCommand = Get-Command $Python -ErrorAction Stop
$PythonExecutable = $PythonCommand.Source
$PythonRoot = Split-Path -Parent $PythonExecutable
$IsolatedPathEntries = @(
    $PythonRoot
    (Join-Path $PythonRoot "Scripts")
    $env:SystemRoot
    (Join-Path $env:SystemRoot "System32")
    (Join-Path $env:SystemRoot "System32\Wbem")
    (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0")
) | Select-Object -Unique
$env:Path = $IsolatedPathEntries -join ";"

Push-Location $ProjectRoot
try {
    & $PythonExecutable (Join-Path $WindowsDir "generate_icon.py")
    if ($LASTEXITCODE -ne 0) {
        throw "La génération de l'icône Windows a échoué."
    }

    & $PythonExecutable -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $Dist `
        --workpath $Work `
        $Spec
    if ($LASTEXITCODE -ne 0) {
        throw "La construction de l'exécutable a échoué."
    }

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "L'exécutable attendu n'a pas été créé : $Executable"
    }

    Remove-Item -LiteralPath $SelfTestReport -Force -ErrorAction SilentlyContinue
    $SelfTest = Start-Process `
        -FilePath $Executable `
        -ArgumentList @("--self-test-report", $SelfTestReport) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($SelfTest.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $SelfTestReport -PathType Leaf)) {
        throw "L'auto-diagnostic de l'EXE a échoué (code $($SelfTest.ExitCode))."
    }
    $SelfTestData = Get-Content -LiteralPath $SelfTestReport -Raw | ConvertFrom-Json
    if (
        -not $SelfTestData.success `
        -or -not $SelfTestData.ffmpeg_embedded `
        -or -not $SelfTestData.desktop_startup.success
    ) {
        throw "L'auto-diagnostic UI, Studio ou codecs du bundle a échoué."
    }

    $Stopwatch.Stop()
    $File = Get-Item -LiteralPath $Executable
    $Hash = Get-FileHash -LiteralPath $Executable -Algorithm SHA256
    @{
        executable = $File.FullName
        size_bytes = $File.Length
        build_seconds = [Math]::Round($Stopwatch.Elapsed.TotalSeconds, 1)
        sha256 = $Hash.Hash
        isolated_build_path = $true
        codec_self_test = $SelfTestData
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $BuildReport -Encoding UTF8
    Write-Host ""
    Write-Host "ArtAnimate Windows est prêt."
    Write-Host "Fichier : $($File.FullName)"
    Write-Host "Taille  : $([Math]::Round($File.Length / 1MB, 1)) Mo"
    Write-Host "Build   : $([Math]::Round($Stopwatch.Elapsed.TotalSeconds, 1)) s"
    Write-Host "SHA-256 : $($Hash.Hash)"
    Write-Host "Codecs  : FFmpeg $($SelfTestData.ffmpeg_version) embarqué et vérifié"
    Write-Host "UI      : fenêtre principale et espace Studio chargés"
    Write-Host "Rapport : $BuildReport"
}
finally {
    $env:Path = $OriginalPath
    Pop-Location
}
