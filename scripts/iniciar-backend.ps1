# Inicia o backend em modo automatico com as escolhas salvas em data/system_config.local.json.
# Usado pelo atalho de inicializacao do Windows (scripts/instalar-inicializacao.ps1).
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Crie a .venv e instale requirements.txt.' }
$host.UI.RawUI.WindowTitle = 'InteliEsteira backend'
# Uma variavel herdada (ex.: AUTO_OPERATION=0 de testes) nao pode desligar o automatico.
Remove-Item Env:AUTO_OPERATION -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING = 'utf-8'
$logDir = Join-Path $projectRoot 'output\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'backend.log'
# Um backend recem-encerrado pode segurar o log por alguns segundos; sem esperar,
# o redirecionamento do cmd falha e o Python nem chega a iniciar.
for ($i = 0; $i -lt 20; $i++) {
    try { [IO.File]::Open($log, 'OpenOrCreate', 'ReadWrite', 'None').Close(); break }
    catch { Start-Sleep -Milliseconds 500 }
}
if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 10MB) {
    Move-Item -Force -LiteralPath $log -Destination "$log.1"
}
Set-Location -LiteralPath $projectRoot
Write-Host "InteliEsteira rodando em http://127.0.0.1:5000 - log em $log"
Write-Host 'Feche esta janela para parar o backend.'
# Log em arquivo: no console, um clique na janela (Edicao Rapida) bloqueia toda
# escrita e congela as requisicoes do backend.
cmd /c "`"$python`" -u start.py >> `"$log`" 2>&1"
