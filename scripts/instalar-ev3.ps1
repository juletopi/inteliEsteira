param(
    # Endereco para alcancar o EV3 agora: IPv4 ou IPv6 link-local do Bluetooth
    # (ex.: fe80::7adb:2fff:fe1c:498b%20, visto com Get-NetNeighbor).
    [string]$Ev3Host = '192.168.137.3',
    # IP fixo gravado no EV3 para a rede Bluetooth (o PC fica em 192.168.137.1).
    [string]$IpFixo = '192.168.137.3',
    [string]$User = 'robot',
    [int]$Port = 8765
)
# Prepara um EV3 (imagem ev3dev/EV3 MicroPython recem-gravada) para a InteliEsteira:
#   - ponte TCP (ev3/*.py) como servico que sobe no boot;
#   - chave SSH deste PC (depois disso nao pede mais senha no SSH);
#   - desligamento seguro: bateria baixa ou 30 min sem o backend (protege o cartao SD);
#   - log do sistema so em memoria e permissao para o PC desligar o EV3;
#   - IP fixo na rede Bluetooth.
# Pede a senha do EV3 (padrao: maker) no SSH e no sudo. Execute num terminal interativo:
#   powershell -ExecutionPolicy Bypass -File scripts\instalar-ev3.ps1 -Ev3Host <endereco>
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$ev3Dir = Join-Path $projectRoot 'ev3'
$files = @('server.py', 'bridge.py', 'main.py', 'calibration.py', 'token.txt', 'inteliesteira.service.example',
           'sistema/inteliesteira-energia.sh', 'sistema/inteliesteira-energia.service',
           'sistema/journald-inteliesteira.conf', 'sistema/sudoers-inteliesteira')
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $ev3Dir $name))) { throw "Arquivo ausente: ev3\$name" }
}
$token = (Get-Content -LiteralPath (Join-Path $ev3Dir 'token.txt') -Raw).Trim()
if ($token -notmatch '^[A-Za-z0-9_-]{16,128}$') { throw 'ev3\token.txt invalido.' }
if ($IpFixo -notmatch '^192\.168\.137\.([2-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-4])$') { throw 'Use um IP fixo em 192.168.137.2-254.' }

$keyFile = Join-Path $HOME '.ssh\id_ed25519.pub'
if (-not (Test-Path -LiteralPath $keyFile)) {
    Write-Host 'Gerando chave SSH deste PC...'
    ssh-keygen -t ed25519 -N '""' -f (Join-Path $HOME '.ssh\id_ed25519') | Out-Null
}
$publicKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+( [^''"]*)?$') { throw "Chave publica inesperada em $keyFile" }

$remoteDir = '/home/robot/inteliEsteira/ev3'
$target = "${User}@${Ev3Host}"

# 1) Arquivos + chave (senha do SSH). tar -m: o relogio do EV3 costuma estar atrasado.
$copy = "mkdir -p $remoteDir ~/.ssh && chmod 700 ~/.ssh && " +
    "(grep -qxF '$publicKey' ~/.ssh/authorized_keys 2>/dev/null || echo '$publicKey' >> ~/.ssh/authorized_keys) && " +
    "chmod 600 ~/.ssh/authorized_keys && tar -m -xf - -C $remoteDir && chmod 600 $remoteDir/token.txt && " +
    "sed -i 's/\r$//' $remoteDir/sistema/* && echo ARQUIVOS_OK"
Write-Host "Copiando ev3\ para ${target}:$remoteDir (senha do EV3)..."
# cmd.exe preserva os bytes do tar no pipe; o PowerShell 5 os corromperia.
Push-Location -LiteralPath $ev3Dir
try {
    cmd /c "tar -cf - $($files -join ' ') | ssh -o ConnectTimeout=8 $target `"$copy`""
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar os arquivos para o EV3.' }
}
finally { Pop-Location }

# 2) Servicos e protecoes (sudo pede a senha). A chave ja vale para o SSH.
# So o processo da ponte comeca com pybricks-micropython; a ancora ^ evita que o
# pkill encontre a linha de comando deste proprio shell remoto.
$killBridge = "pkill -f '^(/usr/bin/)?pybricks-micropython .*server[.]py' || true"
$s = "$remoteDir/sistema"
$setup = @(
    "set -e",
    "sudo -v",
    # Ponte TCP como servico de boot.
    "sudo cp $remoteDir/inteliesteira.service.example /etc/systemd/system/inteliesteira.service",
    # Desligamento seguro (bateria baixa / sem backend).
    "sudo install -m 755 $s/inteliesteira-energia.sh /usr/local/bin/inteliesteira-energia",
    "sudo install -m 644 $s/inteliesteira-energia.service /etc/systemd/system/inteliesteira-energia.service",
    # Log do sistema so em memoria.
    "sudo mkdir -p /etc/systemd/journald.conf.d",
    "sudo install -m 644 $s/journald-inteliesteira.conf /etc/systemd/journald.conf.d/inteliesteira.conf",
    # Permissao para o PC desligar o EV3 sem senha (validada antes de instalar).
    "sudo visudo -cf $s/sudoers-inteliesteira",
    "sudo install -m 440 $s/sudoers-inteliesteira /etc/sudoers.d/inteliesteira",
    "$killBridge",
    "sudo systemctl daemon-reload",
    "sudo systemctl restart systemd-journald",
    "sudo systemctl enable inteliesteira inteliesteira-energia",
    "sudo systemctl restart inteliesteira inteliesteira-energia",
    "sleep 15",
    "systemctl is-active inteliesteira inteliesteira-energia || true",
    # IP fixo na rede Bluetooth (ultimo passo: pode reiniciar a conexao).
    # Sem aspas duplas: o PowerShell 5 nao as repassa intactas ao ssh.exe.
    "if connmanctl services | grep -q bluetooth_; then sudo connmanctl config `$(connmanctl services | awk '/bluetooth_/ {print `$NF; exit}') --ipv4 manual $IpFixo 255.255.255.0 192.168.137.1 && echo IP_FIXO_OK; else echo Servico Bluetooth nao encontrado no connman, IP fixo nao aplicado; fi"
) -join '; '
Write-Host 'Instalando servicos e protecoes (o sudo pede a senha do EV3)...'
ssh -t $target $setup

Write-Host "Testando ${IpFixo}:$Port..."
Start-Sleep -Seconds 5
$client = New-Object System.Net.Sockets.TcpClient
try {
    $client.ConnectAsync($IpFixo, $Port).Wait(8000) | Out-Null
    if ($client.Connected) { Write-Host "OK: ponte do EV3 em ${IpFixo}:$Port, com desligamento seguro ativo." -ForegroundColor Green }
    else { throw 'timeout' }
}
catch {
    Write-Host "A porta $Port em $IpFixo ainda nao responde. Confira a conexao Bluetooth e rode de novo." -ForegroundColor Red
    exit 1
}
finally { $client.Close() }
