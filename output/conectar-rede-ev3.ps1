$ErrorActionPreference='Stop'
$logPath=Join-Path $PSScriptRoot 'conectar-rede-ev3.log'
try {
    $adapter=Get-NetAdapter | Where-Object { $ErrorActionPreference='Stop'
$logPath=Join-Path $PSScriptRoot 'conectar-rede-ev3.log'
try {
    $adapter=Get-NetAdapter -Name 'Conexão de Rede Bluetooth'
    if ($adapter.InterfaceDescription -notmatch 'Bluetooth') { throw 'Adaptador inesperado.' }
    $existing=Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object IPAddress -eq '169.254.209.1'
    if (-not $existing) {
        New-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -IPAddress '169.254.209.1' -PrefixLength 16 -PolicyStore ActiveStore | Out-Null
    }
    'OK: endereco 169.254.209.1/16 adicionado somente ao Bluetooth nesta sessao.' | Set-Content -LiteralPath $logPath
} catch { $_.Exception.Message | Set-Content -LiteralPath $logPath; exit 1 }
.ifIndex -eq 19 }
    if ($adapter.InterfaceDescription -notmatch 'Bluetooth') { throw 'Adaptador inesperado.' }
    $existing=Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object IPAddress -eq '169.254.209.1'
    if (-not $existing) {
        New-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -IPAddress '169.254.209.1' -PrefixLength 16 -PolicyStore ActiveStore | Out-Null
    }
    'OK: endereco 169.254.209.1/16 adicionado somente ao Bluetooth nesta sessao.' | Set-Content -LiteralPath $logPath
} catch { $_.Exception.Message | Set-Content -LiteralPath $logPath; exit 1 }

