<h2>Changelog</h2>

<details open>
<summary>
  <h3 style="display: inline-block;">[v0.4.0] - 29/10/2026</h3>
</summary>

<h3>Adicionado</h3>

- Animações no Dashboard para a apresentação, mantendo o visual original:
  - entrada escalonada dos blocos, contagem animada nos cards de métricas e brilho periódico nos cards
  - Caminho do cubo com faixa em movimento durante a operação, ícone da etapa ativa animado
    (pulso do sensor, garra balançando, leitura do ArUco, esteira andando), selo de etapa concluída
    e setas entre as etapas que acompanham o progresso
  - varredura na prévia da câmera durante a leitura do ArUco e ponto pulsante nos componentes conectados
  - Etapas por região com brilho na barra de progresso, placar que pulsa a cada entrega,
    bandeiras em cinza até a entrega e bandeira tremulando na chegada
  - cubo novo entrando com animação na Linha de produção
  - animações desligadas quando o sistema pede movimento reduzido (`prefers-reduced-motion`)
- Visão geral do Dashboard numa tela só (a partir de 1200 px de largura):
  - duas colunas: métricas, Caminho do cubo e as 5 regiões em uma linha à esquerda;
    câmera e os 3 últimos cubos da linha de produção à direita
  - status de cada componente (HC-SR04, braço, webcam, esteira) embaixo da etapa correspondente
  - "Garra em movimento" sobreposta à câmera e aviso de entrega sobre o cabeçalho das regiões, sem deslocar o layout
  - compactação extra em telas baixas (ex.: projetor 1366×768)
  - fila automática e controles do operador logo abaixo da visão geral
- Bootstrap 5.3.3, Bootstrap Icons 1.11.3 e jQuery 3.7.1 servidos de `app/static/vendor/`,
  sem depender de internet

<h3>Alterado</h3>

- `layout.html` e o calibrador (`app/static/mearm_calibrador.html`) deixam de carregar bibliotecas e ícones por CDN

</details>

<details open>
<summary>
  <h3 style="display: inline-block;">[v0.3.0] - 21/10/2026</h3>
</summary>

<h3>Adicionado</h3>

- Operação coletiva automática validada na bancada: HC-SR04 → MeArm → ArUco → EV3, ciclos de ~20 s
- `SISTEMA:LIBERAR` (firmware, API e botão **Soltar servos**) para refazer a referência do neutro
- Confirmação automática do neutro (`AUTO_SYNC_NEUTRAL`) e rearme do fluxo no boot do backend
- Reconexão automática quando um controlador cai sem cubo em andamento
- HC-SR04 com mediana, histerese de 2 cm, distância ao vivo no Dashboard e `PRESENCA:LEITURA`
- Scripts `instalar-ev3.ps1` (ponte + serviço systemd + chave SSH), `gravar-firmware.ps1`,
  `iniciar-backend.ps1` e `instalar-inicializacao.ps1`
- Firmware compilado versionado em `arduino/firmware/` e guia `docs/operacao-automatica.md`

<h3>Corrigido</h3>

- Fundo da bancada (9 cm) dentro do limite do sensor (10 cm) prendia o estado em "cubo detectado"; limite passa a 5 cm
- RAM do firmware de 1535 para ~790 bytes estáticos (literais na flash, buffers menores)
- Um único PING atrasado encerrava o fluxo (`HEARTBEAT_FAILED`)
- Console do Windows em seleção congelava o backend; log passa a `output/logs/backend.log`
- Boot após encerramento abrupto não rearmava o fluxo enquanto a posse anterior valia
- Simulador serial não respondia `SISTEMA:STATUS` repetido; testes atualizados para o fluxo por perfil

</details>

<details open>
<summary>
  <h3 style="display: inline-block;">[v0.2.0] - 17/09/2026</h3>
</summary>

<h3>Adicionado</h3>

- Validação do contrato JSON de QR Code com produto e UF
- Mapeamento das 27 UFs para cinco macrorregiões e dez destinos físicos
- Seleção de destino por disponibilidade e menor ocupação
- Máquina de estados do ciclo operacional
- Protocolo de comandos, confirmações, eventos e erros
- Simuladores de Arduino e webcam
- Timeouts, repetição de comandos, parada segura e reset
- Endpoints para rota, execução de ciclo, parada e reset
- Dashboard conectado à API com controles operacionais e status em tempo real
- Banco SQLite para produtos, ciclos e eventos operacionais
- Cadastro, listagem, ativação e desativação de produtos
- QR Code reduzido ao identificador; a UF passa a vir do cadastro confiável
- Histórico real e persistente na página da linha de produção
- Testes automatizados do domínio, protocolo, controller, API e interface
- Geração e download de QR Code PNG a partir do cadastro de produtos
- Adaptador de webcam real com OpenCV e leitura contínua até o timeout
- Preview da webcam real no dashboard
- Configuração independente de câmera simulada ou real
- Supressão temporária de leituras duplicadas na webcam
- Teste de integração que gera um QR e o decodifica novamente com OpenCV
- Adaptador pyserial para Arduino real com leitor assíncrono
- Correlação de ACK, EVT e ERR por identificador de ciclo
- Timeout, retransmissão e cancelamento da espera por sensores na conexão real
- Inicialização tolerante a Arduino desconectado no modo serial
- Listagem de portas e tentativa de conexão pela tela de diagnóstico
- Firmware de bancada que valida o protocolo sem movimentar hardware
- Testes seriais com porta falsa, incluindo ruído, erro, retry e evento

</details>

<details open>
<summary>
  <h3 style="display: inline-block;">[v0.1.0] - 03/09/2026</h3>
</summary>

<h3>Adicionado</h3>

<h4>Base Flask para execução do projeto</h4>

- Aplicação Flask criada com <code>app/__init__.py</code>
- Arquivo <code>config.py</code> para centralizar <code>FLASK_HOST</code> e <code>FLASK_PORT</code>
- Ponto de entrada em <code>start.py</code> para iniciar o servidor local
- Blueprint de páginas em <code>app/routes/pages.py</code>
- Blueprint de API em <code>app/routes/api.py</code>

<h4>Interface inicial mockada</h4>

- Tela <code>templates/dashboard.html</code> para dashboard com indicadores operacionais
- Tela <code>templates/production.html</code> para o histórico de produtos da linha de produção
- Tela <code>templates/connection.html</code> para diagnóstico e configuração dos componentes

<h4>Estrutura inicial dos componentes de hardware</h4>

- Módulo de comunicação serial em <code>hardware/arduino.py</code>
- Módulo da garra em <code>hardware/gripper.py</code>
- Módulo da esteira em <code>hardware/conveyor.py</code>
- Módulo de câmera e leitura de QR Code em <code>vision/qrcode.py</code>
- Estado compartilhado em <code>core/state.py</code>
- Controller para coordenar câmera, classificação, garra e esteira em <code>core/controller.py</code>
- Classificador para relacionar QR Code, produto e destino em <code>core/classifier.py</code>

<h4>Comandos planejados para os hardwares</h4>

- Estrutura inicial para comandos de garra: <code>GARRA:PEGAR</code>, <code>GARRA:SOLTAR</code> e <code>GARRA:HOME</code>
- Estrutura inicial para comandos de esteira: <code>ESTEIRA:START</code> e <code>ESTEIRA:STOP</code>
- Estrutura reservada para comandos de destino como <code>DESTINO:NORTE</code> e <code>DESTINO:SUL</code>
- Estrutura reservada para respostas <code>OK:*</code> e erros <code>ERRO:*</code> do Arduino
- Sketch inicial em <code>arduino/mock.ino</code> para futura implementação do protocolo serial

</details>
