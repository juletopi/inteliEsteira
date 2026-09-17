<div align="center">
	<h2 align="center">InteliEsteira</h2>
	<p align="center">
		Projeto de monitoramento e automação de esteira LEGO com garra, câmera e Arduino.
	</p>
</div>

<div align="center">
	<a href="https://www.python.org/">
		<img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python-badge">
	</a>
	<a href="https://flask.palletsprojects.com/">
		<img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask-badge">
	</a>
	<a href="https://www.arduino.cc/">
		<img src="https://img.shields.io/badge/Arduino-00979D?style=for-the-badge&logo=arduino&logoColor=white" alt="Arduino-badge">
	</a>
</div>

<br>

<div align="center">
	<a href="#sobre-o-projeto">Sobre</a> &#xa0; • &#xa0;
    <a href="#estrutura-do-projeto">Estrutura</a> &#xa0; • &#xa0;
	<a href="#instalação">Instalação</a> &#xa0; • &#xa0;
	<a href="#changelog">Changelog</a>
</div>

---

## Sobre o projeto

O **InteliEsteira** é um projeto para monitorar e automatizar uma linha de produção com esteira, garra mecânica, câmera e Arduino.

O sistema segue uma separação de responsabilidades:

```text
Interface web
		↓ HTTP / JSON
Flask
		↓ lógica de negócio
Controller
		↓ comandos semânticos
Arduino
		↓
Garra • Esteira • Câmera
```

### Funcionalidades

- Interface web de monitoramento e controle da linha de produção:
   - **Dashboard** responsivo conectado ao backend simulado.
   - Controles para validar QR, executar ciclo, parar e resetar o sistema.
   - Indicadores em tempo real de estado, componentes e último destino.
   - **Linha de produção** com histórico persistente de produtos processados.
   - **Produtos** para cadastrar identificadores, UFs e ativar/desativar itens.
   - Geração de etiquetas QR em PNG para cada produto cadastrado.
   - **Conexão** com diagnóstico, reconexão e listagem das portas seriais.
- Estrutura de comunicação serial:
   - Camada `core` para estado, classificação e coordenação do sistema.
   - Camada `hardware` para comunicação serial, garra e esteira.
   - Adaptador real com pyserial, leitura em segundo plano, timeout e repetição.
   - Camada `vision` para captura de imagens e leitura de QR Code.
   - Leitura contínua pela webcam com OpenCV, preview e bloqueio de duplicatas.
- Roteamento inicial de produtos:
   - Validação de QR Codes JSON contendo somente o identificador do produto.
   - Consulta da UF em um cadastro persistente, sem confiar o destino ao QR.
   - Conversão das 27 UFs para as cinco macrorregiões brasileiras.
   - Distribuição entre dez destinos físicos, de `R01` a `R10`.
   - Escolha do destino disponível com menor ocupação.

### Contrato do QR Code

```json
{
  "produto_id": "PROD-0087"
}
```

O produto precisa estar cadastrado antes da leitura. O backend consulta a UF no
SQLite, encontra a macrorregião e escolhe uma das duas saídas físicas associadas:

```text
NORTE        -> R01, R02
SUL          -> R03, R04
SUDESTE      -> R05, R06
NORDESTE     -> R07, R08
CENTRO_OESTE -> R09, R10
```

Cadastre primeiro o produto:

```http
POST /api/products
Content-Type: application/json

{
  "produto_id": "PROD-0087",
  "uf": "CE"
}
```

Gere a etiqueta correspondente pela tela **Produtos** ou pela API:

```http
GET /api/products/PROD-0087/qrcode
GET /api/products/PROD-0087/qrcode?download=1
```

O PNG sempre codifica o JSON canônico `{"produto_id":"PROD-0087"}`. A UF não
fica na etiqueta: ela continua protegida no cadastro do backend.

Depois, para testar a resolução de rota sem conectar o hardware:

```http
POST /api/route
Content-Type: application/json

{
  "qr_code": "{\"produto_id\":\"PROD-0087\"}",
  "ocupacao": {"R07": 2, "R08": 1},
  "indisponiveis": []
}
```

Resposta esperada:

```json
{
  "ok": true,
  "produto": {"id": "PROD-0087", "uf": "CE"},
  "macroregiao": "NORDESTE",
  "destino": "R08",
  "candidatos": ["R07", "R08"]
}
```

### Ciclo completo no simulador

O projeto inicia com `HARDWARE_MODE = "mock"`. Nesse modo, a aplicação executa
o fluxo de garra, câmera, classificação, esteira e sensor de chegada sem exigir
um Arduino conectado.

```http
POST /api/cycles
Content-Type: application/json

{
  "qr_code": "{\"produto_id\":\"PROD-0087\"}",
  "ocupacao": {"R07": 2, "R08": 1},
  "indisponiveis": []
}
```

O ciclo percorre os estados:

```text
IDLE
  -> AGUARDANDO_OBJETO
  -> PEGANDO_OBJETO
  -> OBJETO_POSICIONADO
  -> LENDO_QR
  -> VALIDANDO_QR
  -> DESTINO_DEFINIDO
  -> TRANSPORTANDO
  -> FINALIZADO
```

Comandos produzidos para o Arduino simulado:

```text
CMD:<ciclo>:GARRA:PEGAR
CMD:<ciclo>:GARRA:SOLTAR
CMD:<ciclo>:GARRA:HOME
CMD:<ciclo>:DESTINO:R08
CMD:<ciclo>:ESTEIRA:START
EVT:<ciclo>:DESTINO_ALCANCADO:R08
CMD:<ciclo>:ESTEIRA:STOP
```

Para parada e recuperação:

```text
POST /api/system/stop
POST /api/system/reset
```

Falhas de câmera, comandos rejeitados e ausência da confirmação do sensor levam
o sistema ao estado `ERRO`, param a esteira e exigem um reset antes do próximo
ciclo.

### Webcam real com OpenCV

O Arduino pode continuar simulado enquanto a webcam já funciona de verdade.
No PowerShell, inicie assim:

```powershell
$env:CAMERA_MODE = "opencv"
$env:CAMERA_INDEX = "0"
python start.py
```

Nesse modo, `POST /api/cycles` não aceita `qr_code` no corpo. A execução move a
garra, posiciona o objeto e o backend procura o QR diretamente nos frames:

```http
POST /api/cycles
Content-Type: application/json

{
  "ocupacao": {},
  "indisponiveis": []
}
```

Parâmetros disponíveis:

```text
CAMERA_MODE=mock|opencv
CAMERA_INDEX=0
CAMERA_SCAN_TIMEOUT=8.0
CAMERA_RETRY_INTERVAL=0.08
CAMERA_DUPLICATE_COOLDOWN=3.0
```

O tempo de duplicata evita que uma etiqueta parada diante da lente inicie dois
processamentos seguidos. Retire o produto do enquadramento antes de apresentar
o próximo. O preview usa `GET /api/camera/frame` e só existe no modo `opencv`.

### Arduino real pela porta serial

O modo `serial` conecta o mesmo controller a um Arduino real, sem alterar a
lógica de classificação. Primeiro grave [arduino/mock.ino](arduino/mock.ino) no
Arduino UNO. Esse firmware é próprio para bancada: ele valida o protocolo e
simula as confirmações, mas não configura nem energiza nenhum pino.

Na tela **Conexão**, use **Listar portas** para descobrir a COM disponível. Em
seguida, reinicie o backend no PowerShell:

```powershell
$env:HARDWARE_MODE = "serial"
$env:ARDUINO_PORT = "COM3"
$env:ARDUINO_BAUDRATE = "9600"
$env:CAMERA_MODE = "mock"
python start.py
```

O firmware e o backend trocam uma linha por mensagem:

```text
Backend  -> CMD:<ciclo>:GARRA:PEGAR
Arduino  -> ACK:<ciclo>:GARRA:PEGAR

Backend  -> CMD:<ciclo>:DESTINO:R07
Arduino  -> ACK:<ciclo>:DESTINO:R07

Backend  -> CMD:<ciclo>:ESTEIRA:START
Arduino  -> ACK:<ciclo>:ESTEIRA:START
Arduino  -> EVT:<ciclo>:DESTINO_ALCANCADO:R07

Arduino  -> ERR:<ciclo>:<comando>:<codigo>
```

O leitor serial trabalha em segundo plano, correlaciona respostas pelo ciclo e
permite que a parada seja enviada enquanto o sistema aguarda um evento. Linhas
de inicialização ou mensagens malformadas são ignoradas, e comandos sem ACK são
repetidos conforme a configuração do controller.

Configurações disponíveis:

```text
HARDWARE_MODE=mock|serial
ARDUINO_PORT=COM3
ARDUINO_BAUDRATE=9600
ARDUINO_READ_TIMEOUT=0.1
ARDUINO_WRITE_TIMEOUT=1.0
ARDUINO_BOOT_WAIT=2.0
```

Endpoints de diagnóstico:

```text
GET  /api/hardware/ports
POST /api/system/connect
GET  /api/status
```

Depois que o time definir pinos, limites e quantidade de passos, o firmware de
bancada deverá receber as ações físicas dos motores e sensores nos pontos em
que hoje apenas envia `ACK` e `EVT`.

### Persistência

O banco `data/inteliesteira.db` é criado automaticamente no primeiro início e
armazena:

- produtos e respectivas UFs;
- ciclos concluídos, parados e com erro;
- macrorregião e destino selecionados;
- eventos operacionais de cada ciclo;
- datas de início e conclusão.

As principais consultas são:

```text
GET /api/products
GET /api/cycles
GET /api/cycles/<ciclo_id>
```

### Tecnologias utilizadas

#### Interface

<a href="https://developer.mozilla.org/pt-BR/docs/Web/HTML">
	<img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5-badge">
</a>
<a href="https://developer.mozilla.org/pt-BR/docs/Web/CSS">
	<img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" alt="CSS3-badge">
</a>
<a href="https://developer.mozilla.org/pt-BR/docs/Web/JavaScript">
	<img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript-badge">
</a>
<a href="https://getbootstrap.com/">
	<img src="https://img.shields.io/badge/Bootstrap-5.3-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" alt="Bootstrap-badge">
</a>
<a href="https://jquery.com/">
	<img src="https://img.shields.io/badge/jQuery-3.7-0769AD?style=for-the-badge&logo=jquery&logoColor=white" alt="jQuery-badge">
</a>

#### Backend e servidor

<a href="https://www.python.org/">
	<img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python-badge">
</a>
<a href="https://flask.palletsprojects.com/">
	<img src="https://img.shields.io/badge/Flask-3.x-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask-badge">
</a>

O backend também usa **OpenCV** para captura/detecção e **qrcode + Pillow** para
gerar as etiquetas PNG.

#### Hardware e embarcados

<a href="https://www.arduino.cc/">
	<img src="https://img.shields.io/badge/Arduino-00979D?style=for-the-badge&logo=arduino&logoColor=white" alt="Arduino-badge">
</a>

<div align="left">
   <h6><a href="#inteliesteira"> Voltar para o início ↺</a></h6>
</div>

## Estrutura do projeto

```text
inteliEsteira/
├── app/
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   └── pages.py
│   └── services/
│       ├── __init__.py
│       └── status.py
├── arduino/
│   └── mock.ino
├── core/
│   ├── __init__.py
│   ├── classifier.py
│   ├── controller.py
│   └── state.py
├── hardware/
│   ├── __init__.py
│   ├── arduino.py
│   ├── conveyor.py
│   ├── gripper.py
│   ├── mock.py
│   ├── protocol.py
│   └── serial_adapter.py
├── templates/
│   ├── connection.html
│   ├── dashboard.html
│   ├── layout.html
│   ├── production.html
│   └── products.html
├── storage/
│   ├── __init__.py
│   ├── database.py
│   └── repositories.py
├── vision/
│   ├── __init__.py
│   ├── mock.py
│   └── qrcode.py
├── tests/
│   ├── test_api.py
│   ├── test_classifier.py
│   ├── test_controller.py
│   ├── test_protocol.py
│   ├── test_qrcode.py
│   ├── test_serial_adapter.py
│   └── test_storage.py
├── .gitignore
├── CHANGELOG.md
├── config.py
├── requirements.txt
├── README.md
└── start.py
```

<div align="left">
   <h6><a href="#inteliesteira"> Voltar para o início ↺</a></h6>
</div>

## Instalação

> [!IMPORTANT]
> Certifique-se de ter os seguintes requisitos antes de iniciar:
> - `pip`.
> - Python 3.10 ou superior.
> - Git, caso o projeto seja clonado de um repositório remoto.

1. Clone o repositório

```bash
git clone https://github.com/juletopi/inteliEsteira.git
cd inteliEsteira
```

2. Instalar dependências

```bash
pip install -r requirements.txt
```

3. Configurar e executar

As configurações iniciais estão em `config.py`:

```python
ARDUINO_PORT = "COM3"
ARDUINO_BAUDRATE = 9600
HARDWARE_MODE = "mock"
CAMERA_INDEX = 0
CAMERA_MODE = "mock"
CAMERA_SCAN_TIMEOUT = 8.0
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
```

Execute o servidor com:

```bash
python start.py
```

Acesse a aplicação em:

```text
http://127.0.0.1:5000
```

4. Executar os testes

```bash
python -m unittest discover -s tests -v
```

Os testes geram uma etiqueta real em memória e confirmam que o OpenCV consegue
decodificar exatamente o mesmo identificador, sem exigir uma webcam conectada.

<div align="left">
   <h6><a href="#inteliesteira"> Voltar para o início ↺</a></h6>
</div>

## Changelog

O projeto mantém um histórico de alterações detalhado para cada versão, incluindo:

- Novas funcionalidades adicionadas
- Alterações em funcionalidades existentes
- Correções de bugs

Consulte o [CHANGELOG.md](CHANGELOG.md) para ver o histórico completo de alterações.

<div align="left">
   <h6><a href="#inteliesteira"> Voltar para o início ↺</a></h6>
</div>
