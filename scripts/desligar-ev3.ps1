param(
    [string]$Ev3Host = '192.168.137.3',
    [string]$User = 'robot'
)
# Desliga o EV3 com seguranca (gravacoes do cartao SD concluidas). Use antes de tirar
# as pilhas ou guardar a bancada. Requer scripts\instalar-ev3.ps1 ja executado
# (chave SSH e permissao de poweroff sem senha).
$ErrorActionPreference = 'Stop'
$target = "${User}@${Ev3Host}"
# Confere acesso e permissao antes: no desligamento o ssh tambem sai com 255.
ssh -o BatchMode=yes -o ConnectTimeout=8 $target 'sudo -n -l /bin/systemctl poweroff' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Sem acesso ao EV3 em $Ev3Host ou sem permissao de desligar; rode scripts\instalar-ev3.ps1." }
ssh -o BatchMode=yes -o ConnectTimeout=8 $target 'sudo -n /bin/systemctl poweroff'
Write-Host 'EV3 desligando. Espere os LEDs apagarem antes de tirar as pilhas.' -ForegroundColor Green
