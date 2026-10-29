# Checkpoint da apresentação — 27/10/2026

Estado validado na bancada: fluxo coletivo automático HC-SR04 → MeArm → ArUco → EV3,
com cada UF entregue na caixa da sua bandeira e o quadro **Etapas por região** no topo do
Dashboard. Tag Git: `apresentacao-2026-10-27`.

## O que está neste ponto

| Parte | Estado |
| --- | --- |
| Backend | Operação automática (`AUTO_OPERATION`, `AUTO_SYNC_NEUTRAL`), leitura do ArUco sem travar, destino fixo por UF |
| Dashboard | Etapas por região no topo, distância ao vivo do HC-SR04, Descartar unidade, Soltar servos |
| Garra | Perfil `data/mearm-flow-profile.json` (entrega com braço em 140°), neutro B90 A94 C120 G123 |
| Sensor | Limite 5 cm (fundo vazio lê ~9–10 cm, cubo 3–4 cm), mediana + histerese de 2 cm |
| Firmware Uno | `arduino/firmware/mearm_calibrador.ino.hex` (SHA-256 começa com `aeab668f`), EEPROM validada |
| EV3 | Ponte como serviço, desligamento seguro, journal em memória, IP fixo `192.168.137.3` |
| Câmera | Logi C270 via DirectShow, índice 0 |

Caixas: RO R01 · AM R02 · SC R03 · PR R04 · SP R05 · MG R06 · BA R07 · PE R08 · MT R09 · GO R10
(tabela completa em `docs/operacao-automatica.md`).

## Backup local (fora do Git)

`output/checkpoints/apresentacao-2026-10-27/`: `system_config.local.json` e `token.txt`
(contêm o token do EV3), `inteliesteira.db` (histórico, catálogo e rodada),
`inteliesteira.json` e o perfil da garra. A pasta é ignorada pelo Git.

## Roteiro no dia

1. Ligar o EV3 e parear o Bluetooth com o PC (o PC fica em `192.168.137.1`). Conferir:
   `ping 192.168.137.3`.
2. Arduino no USB (`COM3`) e webcam C270 no USB.
3. Entrar no Windows: o backend sobe sozinho (ou `scripts\iniciar-backend.ps1`). Em ~10 s o
   fluxo arma com Arduino, câmera e EV3 conectados.
4. Dashboard: `http://127.0.0.1:5000`. Para começar o placar do zero, **Nova rodada**.
5. Colocar um cubo por vez no batente da coleta.
6. Ao terminar: `scripts\desligar-ev3.ps1` antes de tirar as pilhas do EV3.

Se a leitura do ArUco ficar pendente, ajustar a etiqueta do cubo na esteira ou usar
**Descartar unidade** — não usar Parar/Resetar.

## Restaurar este ponto

```powershell
git fetch origin --tags
git checkout apresentacao-2026-10-27
Copy-Item output\checkpoints\apresentacao-2026-10-27\system_config.local.json data\
Copy-Item output\checkpoints\apresentacao-2026-10-27\token.txt ev3\
# Opcional: voltar o histórico/catálogo desta data (backend parado)
Copy-Item output\checkpoints\apresentacao-2026-10-27\inteliesteira.db data\
# Firmware (backend parado) e EV3 recém-gravado:
powershell -ExecutionPolicy Bypass -File scripts\gravar-firmware.ps1 -Port COM3
powershell -ExecutionPolicy Bypass -File scripts\instalar-ev3.ps1 -Ev3Host <endereço>
```

Recomendado antes da apresentação: gravar uma imagem do cartão SD do EV3 funcionando
(balenaEtcher / Win32 Disk Imager) para restaurar em minutos se ele corromper.
