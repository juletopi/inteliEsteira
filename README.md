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
   - **Dashboard** responsivo com indicadores operacionais mockados.
   - **Linha de produção** preparada para o histórico de produtos processados.
   - **Conexão** preparada para diagnóstico e configuração dos componentes.
- Estrutura de comunicação serial:
   - Camada `core` para estado, classificação e coordenação do sistema.
   - Camada `hardware` para comunicação serial, garra e esteira.
   - Camada `vision` para captura de imagens e leitura de QR Code.

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
│   └── gripper.py
├── templates/
│   ├── connection.html
│   ├── dashboard.html
│   ├── layout.html
│   └── production.html
├── vision/
│   ├── __init__.py
│   └── qrcode.py
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
> - Python 3.0.
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
CAMERA_INDEX = 0
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
