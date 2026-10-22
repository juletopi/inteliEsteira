param(
    [string]$Ev3Host = '192.168.137.3',
    [string]$User = 'robot',
    [int]$Port = 8765,
    # Sem o servico systemd a ponte so roda ate o EV3 desligar.
    [switch]$SemServico
)
# Copia a ponte TCP para o EV3, cadastra a chave SSH deste PC e instala o servico
# que sobe a ponte em todo boot. Na primeira vez pede a senha do EV3 (ev3dev: maker)
# para o SSH e, depois, para o sudo. Execute num terminal interativo:
#   powershell -ExecutionPolicy Bypass -File scripts\instalar-ev3.ps1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ev3Dir = Join-Path $projectRoot 'ev3'
$files = @('server.py', 'bridge.py', 'main.py', 'calibration.py', 'token.txt', 'inteliesteira.service.example')
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $ev3Dir $name))) { throw "Arquivo ausente: ev3\$name" }
}
$token = (Get-Content -LiteralPath (Join-Path $ev3Dir 'token.txt') -Raw).Trim()
if ($token -notmatch '^[A-Za-z0-9_-]{16,128}$') { throw 'ev3\token.txt invalido.' }

$keyFile = Join-Path $HOME '.ssh\id_ed25519.pub'
if (-not (Test-Path -LiteralPath $keyFile)) {
    Write-Host 'Gerando chave SSH deste PC...'
    ssh-keygen -t ed25519 -N '""' -f (Join-Path $HOME '.ssh\id_ed25519') | Out-Null
}
$publicKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+( [^''"]*)?$') { throw "Chave publica inesperada em $keyFile" }

$remoteDir = '/home/robot/inteliEsteira/ev3'
# So o processo da ponte comeca com pybricks-micropython; a ancora ^ evita que o
# pkill encontre a linha de comando deste proprio shell remoto.
$killBridge = "pkill -f '^(/usr/bin/)?pybricks-micropython .*server[.]py' || true"
$startManual = "cd $remoteDir && (nohup brickrun -r -- pybricks-micropython server.py > server.log 2>&1 < /dev/null &)"

# 1) Arquivos + chave. tar -m: o relogio do EV3 costuma estar atrasado.
$copy = "mkdir -p $remoteDir ~/.ssh && chmod 700 ~/.ssh && " +
    "(grep -qxF '$publicKey' ~/.ssh/authorized_keys 2>/dev/null || echo '$publicKey' >> ~/.ssh/authorized_keys) && " +
    "chmod 600 ~/.ssh/authorized_keys && tar -m -xf - -C $remoteDir && chmod 600 $remoteDir/token.txt && echo ARQUIVOS_OK"
Write-Host "Copiando ev3\ para ${User}@${Ev3Host}:$remoteDir (senha do EV3, se pedir)..."
# cmd.exe preserva os bytes do tar no pipe; o PowerShell 5 os corromperia.
Push-Location -LiteralPath $ev3Dir
try {
    cmd /c "tar -cf - $($files -join ' ') | ssh -o ConnectTimeout=8 ${User}@${Ev3Host} `"$copy`""
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar os arquivos para o EV3.' }
}
finally { Pop-Location }

# 2) Inicia a ponte: servico systemd (sudo pede a senha) ou processo avulso.
if ($SemServico) {
    $start = "$killBridge; sleep 1; $startManual; sleep 12; tail -n 5 $remoteDir/server.log"
    ssh "${User}@${Ev3Host}" $start
}
else {
    Write-Host 'Instalando servico de boot (o sudo pede a senha do EV3)...'
    $service = "sudo cp $remoteDir/inteliesteira.service.example /etc/systemd/system/inteliesteira.service && " +
        "$killBridge; sudo systemctl daemon-reload && sudo systemctl enable inteliesteira && sudo systemctl restart inteliesteira; " +
        "sleep 15; if systemctl is-active --quiet inteliesteira; then echo SERVICO_ATIVO; " +
        "else echo 'Servico nao ficou ativo; iniciando a ponte avulsa.'; sudo journalctl -u inteliesteira -n 10 --no-pager; $startManual; sleep 12; fi"
    ssh -t "${User}@${Ev3Host}" $service
}

Write-Host "Testando porta $Port..."
$client = New-Object System.Net.Sockets.TcpClient
try {
    $client.ConnectAsync($Ev3Host, $Port).Wait(5000) | Out-Null
    if ($client.Connected) { Write-Host "OK: ponte do EV3 aceitando conexoes em ${Ev3Host}:$Port." -ForegroundColor Green }
    else { throw 'timeout' }
}
catch {
    Write-Host "A porta $Port ainda nao responde. Veja $remoteDir/server.log no EV3." -ForegroundColor Red
    exit 1
}
finally { $client.Close() }
