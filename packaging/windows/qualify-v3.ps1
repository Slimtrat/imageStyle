[CmdletBinding()]
param(
    [string]$Executable = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $WindowsDir "..\..")).Path
if (-not $Executable) {
    $Executable = Join-Path $ProjectRoot "dist\ArtAnimate.exe"
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectRoot "dist\v3-qualification"
}
$Report = Join-Path $OutputDirectory "ArtAnimate-v3-qualification.json"

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Exécutable ArtAnimate introuvable : $Executable"
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
Remove-Item -LiteralPath $Report -Force -ErrorAction SilentlyContinue

$Qualification = Start-Process `
    -FilePath $Executable `
    -ArgumentList @("--qualify-v3", $OutputDirectory) `
    -Wait `
    -PassThru `
    -WindowStyle Hidden

if ($Qualification.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Report -PathType Leaf)) {
    throw "La qualification V3 de l’EXE a échoué (code $($Qualification.ExitCode)). Rapport : $Report"
}
$Data = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
if (-not $Data.success) {
    throw "La qualification V3 est en échec : $($Data.error)"
}

Write-Host "ArtAnimate V3 est qualifié."
Write-Host "Rapport : $Report"
Write-Host "Planche : $($Data.artifacts.visual_contact_sheet)"
Write-Host "Projet  : $($Data.artifacts.project)"
Write-Host "Exports : $($Data.exports.reference.path)"
Write-Host "          $($Data.exports.embedded.path)"
