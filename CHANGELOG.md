<h2>Changelog</h2>

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
