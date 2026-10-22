# Operação automática da bancada

Guia para colocar e manter a InteliEsteira rodando sozinha: HC-SR04 detecta o cubo,
o MeArm pega e entrega na esteira, a câmera lê o ArUco e o EV3 leva ao destino.
Estado validado em 21/10/2026: ciclos completos de ~20 s, um atrás do outro, para
R01, R02, R03, R07, R08 e R09.

## Arquitetura

| Parte | Onde roda | Conexão |
| --- | --- | --- |
| Backend Flask + fila + câmera | PC (Windows) | `http://127.0.0.1:5000` |
| Arduino Uno: MeArm (pinos 10/11/6/3) e HC-SR04 (TRIG 8, ECHO 9) | Uno | USB `COM3`, 9600 baud |
| Ponte da esteira (`ev3/server.py`) | EV3 (Pybricks/ev3dev) | TCP `192.168.137.3:8765`, token |

Protocolo: `CMD:<ciclo>:<comando>` → `ACK` / `EVT` / `ERR`. O fluxo de um cubo:
`SENSOR:PRESENTE` → `GARRA:PERFIL` + `GARRA:AREA:P01` → 4 `GARRA:PASSO:P` →
4 `GARRA:PASSO:E` (termina no neutro) → leitura do ArUco → `DESTINO:Rxx` +
`ESTEIRA:START` no EV3 → `EVT DESTINO_ALCANCADO` → sensor rearmado.

## Configuração validada

- **Perfil da garra:** `data/mearm-flow-profile.json` (CSV de 16/10/2026): 4 passos
  para pegar, 4 para entregar, 24 ms/grau, neutro B90 A94 C120 G123.
- **HC-SR04:** limite **5 cm**, estabilidade 4 s. A área vazia da bancada lê ~9 cm e o
  cubo encostado lê 3–4 cm. A área só volta a "livre" acima de limite + 2 cm (7 cm).
  Se a montagem mudar, confira a distância ao vivo no Dashboard antes de mexer no limite.
- **Firmware:** `arduino/firmware/mearm_calibrador.ino.hex` é o binário gravado no Uno
  (fonte em `arduino/mearm_calibrador/`). A EEPROM guarda Y/X/N, limites e a validação
  `AUTO:VALIDAR`; gravar o firmware não apaga a EEPROM.
- **Configuração local:** `data/system_config.local.json` (fora do Git, contém o token).
  Modelo em `data/system_config.example.json`; `EV3_TOKEN` = conteúdo de `ev3/token.txt`.
  `AUTO_OPERATION` arma o fluxo ao iniciar; `AUTO_SYNC_NEUTRAL` confirma o neutro sem clique.

## Instalação (uma vez por máquina)

1. Python: `python -m venv .venv` e `.venv\Scripts\pip install -r requirements.txt`.
2. Copie `data/system_config.example.json` para `data/system_config.local.json` e preencha
   `EV3_TOKEN` com o conteúdo de `ev3/token.txt` (crie o token se não existir: 16–128
   letras, números, `_` ou `-`).
3. Firmware no Uno (backend parado, calibrador fechado):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\gravar-firmware.ps1 -Port COM3
   ```
4. EV3 ligado na rede do PC (hotspot `192.168.137.x`). Instala a ponte, a chave SSH deste
   PC e o serviço que sobe a ponte em todo boot (pede a senha do EV3 no SSH e no sudo):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\instalar-ev3.ps1
   ```
5. Backend ao entrar no Windows (atalho na pasta Inicialização; `-Remover` desfaz):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\instalar-inicializacao.ps1
   ```
6. Calibração (só se a montagem mudar): módulo **Calibração** do Dashboard → pontos Y/X/N,
   limites, garra → **Validar para operação coletiva** (`AUTO:VALIDAR`) → **Salvar fluxo e
   encerrar**.

## Operação diária

1. Ligue o EV3 (a ponte sobe sozinha) e o Arduino pelo USB.
2. Entre no Windows (ou rode `scripts\iniciar-backend.ps1`). O backend conecta Arduino e EV3
   em segundos; a câmera leva ~1 min para abrir. O fluxo arma sozinho e fica em
   **Aguardando sensor**.
3. Coloque o cubo **sempre no mesmo ponto** da área de coleta (use um batente). O badge do
   HC-SR04 mostra "Detectando…" e, após 4 s, a garra coleta.
4. Coloque o próximo cubo depois que a garra voltar ao neutro. O sensor é rearmado ao fim de
   cada ciclo.

Não feche a janela "InteliEsteira backend": fechar a janela encerra o backend. O log fica em
`output/logs/backend.log` (rotaciona acima de 10 MB).

## Quando algo para

**Leitura do ArUco falhou** (cubo na esteira sem etiqueta legível, marcador sem cadastro):
o fluxo **não trava**. A fila mostra "Leitura do ArUco pendente" e continua tentando ler.
Não use Parar/Resetar: ajuste a etiqueta do cubo na esteira (ou cadastre o marcador em
**Produtos**) e o fluxo segue sozinho para o destino. Para desistir do cubo, retire-o da
esteira e clique em **Descartar unidade**: o fluxo volta a aguardar o sensor.

Outras falhas durante um cubo (comunicação, movimento) param em **ERRO** de propósito: o
cubo pode estar na garra. Retire/reposicione o cubo e use **Resetar operação** →
**Iniciar operação**.

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| Leitura pendente e o sensor ainda vê o cubo na coleta | Garra fechou fora do cubo | Colocar o cubo na esteira (segue sozinho) ou **Descartar unidade**; reposicionar no batente |
| Leitura pendente com o cubo na esteira | Etiqueta suja, virada ou fora da área da câmera | Ajustar o cubo/etiqueta; o fluxo segue sozinho |
| Leitura pendente "não está vinculado a um produto" | ArUco sem produto no catálogo | Cadastrar o marcador em **Produtos** ou **Descartar unidade** |
| "Cubo detectado" com a área vazia | Fundo dentro do limite do sensor | Ver "agora X cm" no Dashboard; limite ≤ fundo − 3 cm no calibrador |
| Fluxo em **Aguardando conexão** | Arduino, EV3 ou câmera fora | Ele reconecta sozinho a cada 2 s; ver o aviso na fila |
| EV3 não conecta | Ponte parada ou EV3 fora da rede | `ping 192.168.137.3`; rodar `scripts\instalar-ev3.ps1` de novo |
| Braço parou no meio do movimento | Parada/erro durante o movimento | **Soltar servos**, alinhar no neutro, **Confirmar braço no neutro** (ou só resetar com `AUTO_SYNC_NEUTRAL`) |

Com `AUTO_SYNC_NEUTRAL`, o sistema assume o braço no neutro salvo; fora dele, o braço salta
para o neutro ao energizar no primeiro movimento.

## Ferramentas de diagnóstico

- `GET /api/diagnostics`: últimas mensagens de cada controlador e estado do sensor.
- `POST /api/sensor/leitura`: mede o HC-SR04 agora (mediana de 9 disparos).
- Histórico de ciclos e eventos: página **Linha de produção** ou `data/inteliesteira.db`.
