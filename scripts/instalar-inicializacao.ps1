param([switch]$Remover)
# Cria (ou remove, com -Remover) o atalho que inicia o backend ao entrar no Windows.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'InteliEsteira backend.lnk'
if ($Remover) {
    Remove-Item -LiteralPath $shortcut -ErrorAction SilentlyContinue
    Write-Host 'Inicializacao automatica removida.'
    return
}
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = (Get-Command powershell.exe).Source
$link.Arguments = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$(Join-Path $PSScriptRoot 'iniciar-backend.ps1')`""
$link.WorkingDirectory = $projectRoot
$link.WindowStyle = 7  # minimizada
$link.Save()
Write-Host "Backend iniciara ao entrar no Windows: $shortcut"
