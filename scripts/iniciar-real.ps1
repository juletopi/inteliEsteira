param(
    [Parameter(Mandatory = $true)][string]$Ev3Host,
    [Parameter(Mandatory = $true)][string]$ArduinoPort,
    [Parameter(Mandatory = $true)][string]$TokenFile,
    [Parameter(Mandatory = $true)][string]$PickupRoi,
    [switch]$ProfilesCalibrated,
    [int]$CameraIndex = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProfilesCalibrated) {
    throw 'Confira o ciclo Y -> X do calibrador e envie AUTO:VALIDAR antes de informar -ProfilesCalibrated.'
}
if ($ArduinoPort -notmatch '^COM[1-9][0-9]*$') { throw 'Informe a porta COM real do Arduino.' }
$token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
if ($token -notmatch '^[A-Za-z0-9_-]{16,128}$') { throw 'Arquivo de token invalido.' }
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Crie a .venv e instale requirements.txt.' }
$names = @('HARDWARE_MODE','ARDUINO_PORT','ARDUINO_BAUDRATE','CONVEYOR_MODE','EV3_HOST',
    'EV3_TOKEN','EV3_PORT','CAMERA_MODE','CAMERA_INDEX','CAMERA_PICKUP_ROI',
    'GRIPPER_PROFILE_CALIBRATED','ARRIVAL_SENSOR_MODE','REQUIRE_PHYSICAL_ARRIVAL')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:HARDWARE_MODE = 'serial'
    $env:ARDUINO_PORT = $ArduinoPort
    $env:ARDUINO_BAUDRATE = '9600'
    $env:CONVEYOR_MODE = 'ev3'
    $env:EV3_HOST = $Ev3Host
    $env:EV3_TOKEN = $token
    $env:EV3_PORT = '8765'
    $env:CAMERA_MODE = 'opencv'
    $env:CAMERA_INDEX = [string]$CameraIndex
    $env:CAMERA_PICKUP_ROI = $PickupRoi
    $env:GRIPPER_PROFILE_CALIBRATED = '1'
    $env:ARRIVAL_SENSOR_MODE = 'arduino'
    $env:REQUIRE_PHYSICAL_ARRIVAL = '1'
    Push-Location -LiteralPath $projectRoot
    try { & $python -m scripts.servidor }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'O backend encerrou com erro.' }
}
finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}
