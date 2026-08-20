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

Push-Location $ProjectRoot
try {
    & $Python (Join-Path $WindowsDir "generate_icon.py")
    if ($LASTEXITCODE -ne 0) {
        throw "La génération de l'icône Windows a échoué."
    }

    & $Python -m PyInstaller `
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

    $File = Get-Item -LiteralPath $Executable
    $Hash = Get-FileHash -LiteralPath $Executable -Algorithm SHA256
    Write-Host ""
    Write-Host "ArtAnimate Windows est prêt."
    Write-Host "Fichier : $($File.FullName)"
    Write-Host "Taille  : $([Math]::Round($File.Length / 1MB, 1)) Mo"
    Write-Host "SHA-256 : $($Hash.Hash)"
}
finally {
    Pop-Location
}
