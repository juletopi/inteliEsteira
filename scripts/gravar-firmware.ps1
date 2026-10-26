param(
    [string]$Port = 'COM3',
    [string]$Hex = ''
)
# Grava o firmware MeArm no Arduino Uno com o avrdude da IDE Arduino.
# A porta precisa estar livre: pare o backend (start.py) e feche o calibrador web.
# A EEPROM (pontos, limites e AUTO:VALIDAR) e preservada.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
# Padrao: o firmware versionado, identico ao gravado na bancada que funcionou.
if (-not $Hex) { $Hex = Join-Path $projectRoot 'arduino\firmware\mearm_calibrador.ino.hex' }
if (-not (Test-Path -LiteralPath $Hex)) { throw "Firmware compilado nao encontrado: $Hex" }
$avrdudeRoot = Get-ChildItem -Directory (Join-Path $env:LOCALAPPDATA 'Arduino15\packages\arduino\tools\avrdude') |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $avrdudeRoot) { throw 'avrdude nao encontrado; instale a placa Arduino AVR na IDE Arduino.' }
$avrdude = Join-Path $avrdudeRoot.FullName 'bin\avrdude.exe'
$config = Join-Path $avrdudeRoot.FullName 'etc\avrdude.conf'
# -D: sem chip erase, para nao tocar na EEPROM com a calibracao.
& $avrdude "-C$config" -patmega328p -carduino "-P$Port" -b115200 -D "-Uflash:w:${Hex}:i"
if ($LASTEXITCODE -ne 0) { throw "avrdude falhou. Confira se $Port esta livre (backend parado, calibrador fechado)." }
Write-Host 'Firmware gravado. Reinicie o backend e confirme o neutro no Dashboard.' -ForegroundColor Green
