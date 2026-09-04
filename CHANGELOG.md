<h2>Changelog</h2>

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
