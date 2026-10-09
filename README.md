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
  ├── serial -> Arduino -> Garra
  ├── TCP/IP -> LEGO EV3 -> Esteira e separador
  └── OpenCV -> Webcam -> QR Code
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
- Integração da esteira LEGO EV3:
   - Ponte TCP no EV3 com autenticação, ACK e evento de conclusão por ciclo.
   - Mapeamento explícito dos destinos do backend para os códigos do colega.
   - Parada durante o movimento, watchdog de comunicação e proteção de reenvios.
   - Simulador TCP para testar a mesma integração sem motores conectados.
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

Para usar ArUco, clique em **Baixar ArUco** na tela **Produtos**. O aplicativo
atribui um ID fixo ao produto e baixa a etiqueta no formato escolhido. Pela API, o mesmo fluxo é:

```http
POST /api/products/PROD-0087/aruco
GET /api/products/PROD-0087/aruco?download=1
```

Na tela **Produtos**, escolha **50, 40, 30 ou 20 mm** e o formato **PDF A4** ou
**PNG** antes de baixar. A opção **Os quatro tamanhos na mesma folha** gera um
PDF com uma etiqueta de cada tamanho, todas vinculadas ao mesmo ID. Um tamanho
individual gera um PDF com quatro cópias. A medida é o lado do quadrado completo,
incluindo a margem branca. Mudar o tamanho não muda o vínculo do produto e não
exige alterar o catálogo.

```http
GET /api/products/PROD-0087/aruco?download=1&format=pdf&size_mm=50
GET /api/products/PROD-0087/aruco?download=1&format=pdf&size_mm=all
GET /api/products/PROD-0087/aruco?download=1&format=png&size_mm=30
```

O PNG registra a medida nos metadados de DPI, que alguns aplicativos de impressão
ignoram. Para obter a medida física, prefira o PDF em **100% / tamanho real**, sem
ajustar à página. Confira a linha de referência de 50 mm com uma régua. Sem
parâmetros, a API continua entregando o PNG original; PDF sem tamanho usa 20 mm.

Para imprimir vários produtos juntos, marque as linhas desejadas ou **Marcar
todos** e clique em **Baixar selecionados (PDF)**. O lote usa o tamanho escolhido,
uma etiqueta por produto (ou quatro tamanhos por produto na opção correspondente).
Cada etiqueta identifica **produto, macrorregião, UF e ID ArUco**. O PDF distribui
os produtos em páginas A4 sem reduzir a medida física se o lote não couber em uma
folha. Identificadores longos são quebrados em linhas, sem truncar.

IDs existentes são mantidos. Produtos sem marcador recebem um ID disponível;
se houver uma etiqueta antiga, informe seu ID no campo da linha antes de baixar
o lote. Os IDs explícitos são reservados antes dos automáticos. Conflitos,
produtos desconhecidos e falta de IDs cancelam todos os novos vínculos do lote.
Se o lote atribuir novos IDs, exporte novamente o catálogo antes de versioná-lo.
Região e UF são consultadas no cadastro, sem usar valores enviados pelo navegador.

```http
POST /api/products/aruco/batch
Content-Type: application/json

{"products": [{"produto_id": "PROD-0087"}, {"produto_id": "PROD-001"}], "size_mm": 30}
```

O identificador do produto (por exemplo, `PROD-0087`, sem espaços) e o ID numérico
ArUco são diferentes. A coluna **ArUco** mostra o ID atribuído; baixar novamente
reutiliza o mesmo vínculo, inclusive após reiniciar o servidor.

Produtos e vínculos ficam em `data/inteliesteira.db`, um arquivo local ignorado
pelo Git. Um `git pull` atualiza o código, mas não copia cadastros de outro
computador ou checkout. Para manter as etiquetas existentes, use o mesmo banco
ou transfira uma cópia dele com os servidores parados. Preserve o banco atual
antes de substituí-lo; essa cópia não mescla os cadastros de dois bancos.
Para criar um backup local com o servidor parado, execute no PowerShell:

```powershell
Copy-Item .\data\inteliesteira.db (".\data\inteliesteira-backup-{0}.db" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
```

Se o banco antigo não estiver disponível, cadastre o produto com o identificador
e UF originais. No campo **ID antigo**, informe o número da etiqueta antes de
clicar em **Baixar ArUco**. O nome `aruco-PROD-0087-id17.png`, por exemplo,
indica o ID 17; esse número é apenas um exemplo. Pela API:

```http
POST /api/products/PROD-0087/aruco
Content-Type: application/json

{"aruco_id": 17}
```

O servidor recusa IDs fora de 0–249, IDs já associados a outro produto e tentativas
de trocar um vínculo existente. Deixar o campo vazio mantém a atribuição
automática. Para reutilizar uma etiqueta antiga, é necessário conhecer o ID
original (e usar o mesmo dicionário `DICT_4X4_250`); só o identificador do produto
não permite deduzir o número que foi atribuído em outro banco.

O marcador usa `DICT_4X4_250` e só é aceito pela câmera quando seu ID está
vinculado a um produto no banco. A leitura resolve o ID para o produto e passa
pela mesma validação de cadastro, atividade e destino usada pelo QR. Um marcador
desconhecido é rejeitado; os IDs disponíveis vão de 0 a 249. A leitura QR
continua disponível na mesma câmera. Para `PROD-0087`, há também uma folha A4
com quatro etiquetas em `output/pdf/etiquetas-aruco-PROD-0087-20mm.pdf`.
Imprima em **100% / tamanho real**, sem "ajustar à página". Cada quadrado
demarcado mede 20 x 20 mm, incluindo a margem branca; confira a linha de 50 mm
com uma régua. Um ArUco de 4 x 4 tem módulos maiores que o QR, mas a webcam
ainda precisa conseguir focalizar o marcador na distância de uso.

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
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_SCAN_TIMEOUT=8.0
CAMERA_RETRY_INTERVAL=0.08
CAMERA_DUPLICATE_COOLDOWN=3.0
```

O tempo de duplicata evita que uma etiqueta parada diante da lente inicie dois
processamentos seguidos. Retire o produto do enquadramento antes de apresentar
o próximo. O preview usa `GET /api/camera/frame` e só existe no modo `opencv`.
`GET /api/status` informa `camera_resolucao` com o tamanho realmente aceito
pela webcam. A resolucao maior nao corrige desfoque por falta de foco da lente.

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

### Esteira LEGO EV3 com Python

O Flask, o cadastro SQLite e a webcam continuam no computador. O código em
`ev3/` roda no EV3 com **Pybricks MicroPython 2.x**, como o programa recebido de
Wasgton Gomes Pereira. Não instale `pybricks` nas dependências do Flask: os
imports de motores só ocorrem quando o programa de hardware é iniciado no EV3.

`HARDWARE_MODE=mock|serial` configura o Arduino da **garra**.
`CONVEYOR_MODE=arduino|mock|ev3` escolhe o controlador da **esteira**. O padrão
`arduino` preserva o comportamento anterior; `ev3` usa uma conexão independente.
No modo `mock`, a esteira tem um simulador independente do Arduino da garra.

O EV3 recebe os mesmos comandos `DESTINO`, `ESTEIRA:START`, `ESTEIRA:STOP` e
`SISTEMA:RESET`, por linhas TCP, não pela porta serial do Arduino. A ponte aceita
um backend por vez. O IP pode ser alcançado pela rede ou por USB configurado
como rede no ev3dev; não basta tratar o cabo USB do EV3 como uma porta COM.
Veja o [guia de rede do ev3dev](https://www.ev3dev.org/docs/networking/).

O mapeamento físico preserva todos os valores numéricos recebidos:

| Macrorregião | Destinos no backend | Códigos locais `codR` no EV3 |
| --- | --- | --- |
| Norte | R01, R02 | 1, 2 |
| Sul | R03, R04 | 9, 10 |
| Sudeste | R05, R06 | 7, 8 |
| Nordeste | R07, R08 | 3, 4 |
| Centro-Oeste | R09, R10 | 5, 6 |

As calibrações estão em `ev3/calibration.py`. Corrigiu-se apenas o rótulo
"Sudoeste" para "Sudeste". O motor A está na porta A; o separador, na porta C.
O fator original `12 * 10` define velocidade em graus/segundo, não força em
porcentagem; as voltas são multiplicadas por 360. Os movimentos agora são não
bloqueantes para que a ponte possa receber uma parada enquanto os motores giram.
Referência: [motores Pybricks 2.x](https://docs.pybricks.com/en/v2.0/ev3devices.html).

#### Preparar o EV3 físico

1. Confirme com o colega o ambiente Pybricks 2.x/ev3dev, as portas dos motores e
   o IP acessível pelo computador. Copie os arquivos Python de `ev3/` para uma
   pasta no EV3, por exemplo `/home/robot/inteliEsteira/ev3`.
2. Crie nessa pasta o arquivo local `token.txt`, com uma chave aleatória de 16
   a 128 letras/números, `_` ou `-`. Use a mesma chave em `EV3_TOKEN` no PC.
   `token.txt` está ignorado pelo Git e nunca deve ser commitado. Para gerar
   uma chave no seu terminal: `python -c "import secrets; print(secrets.token_hex(16))"`.
3. No terminal SSH do EV3, a partir dessa pasta, execute
   `pybricks-micropython server.py`. A ponte escuta na porta TCP 8765.
   Opcionalmente, restrinja o IP de escuta: `pybricks-micropython server.py <IP_DO_EV3> 8765`.
4. No PowerShell do computador, configure e inicie o backend:

```powershell
$env:HARDWARE_MODE = "serial"
$env:ARDUINO_PORT = "COM3"                 # Porta real da garra.
$env:CONVEYOR_MODE = "ev3"
$env:EV3_HOST = "<IP_DO_EV3>"
$env:EV3_PORT = "8765"
$env:EV3_TOKEN = "<MESMA_CHAVE_DO_TOKEN_TXT>"
$env:CAMERA_MODE = "opencv"
$env:ARRIVAL_TIMEOUT = "35"
.\.venv\Scripts\python.exe start.py
```

Use **Conexão → Tentar conectar**. Depois de inspecionar a montagem e posicionar
manualmente a referência inicial, use **Resetar** e execute um produto por vez.
O frontend continua chamando `POST /api/cycles`; não envia `codR` nem escolhe a
UF por conta própria. O backend só movimenta a garra depois de conectar ambos
os controladores. Sem firmware físico da garra, `HARDWARE_MODE=mock` permite
testar apenas a esteira real, mas a coleta/soltura do objeto será simulada.

`GET /api/status` diferencia `arduino` e `esteira_conectada`, informa
`esteira_modo`, `ev3_host`, `ev3_porta` e nunca expõe a chave. `POST
/api/system/reset` atinge os dois controladores sem repetir o comando quando
eles são o mesmo Arduino. Reset limpa a operação lógica e freia os motores;
**não executa homing físico** nem reenfileira um produto interrompido.

A conexão usa uma chave compartilhada, mas **não tem TLS**. Restrinja-a a uma
rede confiável, não exponha a porta à Internet e não compartilhe a chave.
Heartbeats ocorrem a cada segundo; a ponte tenta frear os dois motores ao
detectar desconexão ou após quatro segundos sem mensagem válida. O movimento
também tem limite local de 30 segundos. Isso não substitui parada física de
emergência e não garante frenagem em caso de falha elétrica/mecânica.

Os últimos 128 ciclos são lembrados em RAM para impedir que um reenvio de
`START` repita a ação. Um ciclo interrompido não pode ser reiniciado com o mesmo
ID. Após reconexão é necessário resetar. Reiniciar a ponte perde esse histórico:
inspecione o objeto e a referência física antes de uma nova operação.

**Limite da validação atual:** `DESTINO_ALCANCADO` significa que o EV3 terminou
as rotações calibradas; o código recebido não tem sensor de chegada. O status
e o histórico identificam a confirmação como `movimento_calibrado`. Precisão
da posição, escorregamento, referência inicial, retorno do separador e os
valores de Sul 1/Sul 2 ainda precisam ser conferidos na bancada. Não alteramos
essas calibrações nem inventamos uma rotina de homing.

#### Testar a integração sem LEGO

Em um primeiro terminal, na raiz do projeto:

```powershell
$env:EV3_TOKEN = "chave-apenas-teste-local-1234"
.\.venv\Scripts\python.exe -m ev3.simulator
```

Em outro terminal, também na raiz:

```powershell
$env:HARDWARE_MODE = "mock"
$env:CAMERA_MODE = "mock"
$env:CONVEYOR_MODE = "ev3"
$env:EV3_HOST = "127.0.0.1"
$env:EV3_PORT = "8765"
$env:EV3_TOKEN = "chave-apenas-teste-local-1234"
.\.venv\Scripts\python.exe start.py
```

Cadastre um produto na tela **Produtos** e execute-o no **Dashboard**. O ciclo
usa TCP de verdade, mas sem motores ou webcam real. O simulador escuta apenas
no próprio computador. A chave de exemplo serve somente para esse teste local.
Para voltar ao modo anterior, defina `$env:CONVEYOR_MODE = "arduino"` e reinicie.

Os testes automatizados incluem a API, TCP em localhost, dez destinos,
calibrações, ACK perdido, cancelamento, watchdog, falhas e reconexão:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### Persistência

Para manter os mesmos produtos e IDs ArUco em outro computador ou no dia da
apresentação, siga o [roteiro de catálogo, backup e conferência](docs/apresentacao.md).
O comando `python -m storage.catalog` exporta, importa e verifica os vínculos,
além de criar um backup SQLite consistente sem sobrescrever arquivos anteriores.

Na tela **Produtos**, **Desativar/Ativar** altera a disponibilidade mantendo o
item visível. **Excluir** pede confirmação e remove o produto do catálogo e da
seleção de impressão. O histórico continua disponível. O identificador do
produto e seu ID ArUco ficam reservados; etiquetas antigas não passam a representar
outro produto, e um identificador excluído não pode ser cadastrado novamente.

`DELETE /api/products/<produto_id>` exclui o produto; para apenas desativar, use
`PUT /api/products/<produto_id>` com `{"ativo": false}`. Ao iniciar, o aplicativo
atualiza o banco existente sem apagar produtos ou histórico. Após excluir, exporte
um novo catálogo: registros com `"excluido": true` transportam a exclusão e a reserva
do marcador para a outra máquina. Eles ficam fora da lista da interface. Importar
um catálogo anterior não reativa produtos já excluídos.

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
├── ev3/
│   ├── bridge.py
│   ├── calibration.py
│   ├── main.py
│   ├── server.py
│   └── simulator.py
├── core/
│   ├── __init__.py
│   ├── classifier.py
│   ├── controller.py
│   └── state.py
├── hardware/
│   ├── __init__.py
│   ├── arduino.py
│   ├── conveyor.py
│   ├── device.py
│   ├── ev3_adapter.py
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
│   ├── test_ev3.py
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
