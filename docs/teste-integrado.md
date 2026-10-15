# Testar o painel, a garra e a esteira

O controle de cada unidade passa por HTTP (painel/Flask), serial (Arduino/garra)
e TCP autenticado (Flask/EV3). O programa `server.py` deve estar ativo no EV3;
ele aguarda comandos e nao inicia transporte por conta propria. `main.py` e o
teste manual que pede um codigo de regiao no terminal.

## 1. Testar agora, sem os equipamentos

Na raiz do projeto, com as dependencias da `.venv` instaladas:

```powershell
.\.venv\Scripts\python.exe -m scripts.bancada --smoke-test
```

O comando usa sockets locais de verdade para os dois controladores, banco
temporario e camera simulada. Testa dez ciclos automaticos pelo HC-SR04,
balanceamento R01–R10, leitura apos a coleta e registro de chegada simulada. Nao acessa a COM, o
EV3 fisico ou `data/inteliesteira.db`. Finaliza e encerra os simuladores.

Para acompanhar a operacao automatica pelo painel:

```powershell
.\.venv\Scripts\python.exe -m scripts.bancada
```

Abra http://127.0.0.1:5001. A fila e criada pela identificacao, sem cadastro manual
ou botoes no bloco da camera. Injete etiqueta e presenca pelas APIs de simulacao
do [guia de operacao automatica](operacao-fila.md). O transporte e a chegada
exibidos aqui sao simulados. Falhas exigem inspecao e recuperacao pelas APIs de manutencao.

A bancada salva automaticamente os cadastros em `data/inteliesteira.json`, o mesmo
arquivo da aplicacao principal. Fila e historico simulados ficam separados em
`output/bancada-catalogo.db`, preservados entre aberturas. `--database` permite
outro banco operacional. Para usar apenas produtos TESTE, execute com `--demo`;
esses cadastros ficam separados. O teste automatico sempre usa dados temporarios.
A bancada recusa o banco principal. Nao abra duas instancias com o mesmo banco.

## 2. Testar ArUco com a webcam

```powershell
.\.venv\Scripts\python.exe -m scripts.bancada --camera opencv
```

Na tela Produtos, baixe e imprima as etiquetas dos produtos desse banco. Injete
presenca na API de simulacao e apresente uma etiqueta em E01, apos a coleta virtual.
A leitura vem da camera, enquanto garra, motores e chegada continuam virtuais. Retire a etiqueta anterior do
enquadramento entre unidades. A bancada padrao usa os mesmos produtos e IDs ArUco
do JSON da aplicacao principal; etiquetas ja impressas mantem os vinculos.

`CAMERA_INDEX` seleciona a webcam. `CAMERA_PICKUP_ROI=x,y,largura,altura` delimita
o retangulo em fracoes de 0 a 1. O padrao `0,0,1,1` usa o frame inteiro: ajuste
esse valor a area E01 na esteira. A moldura aparece no preview. A coleta fixa em
P01 e autorizada pelo HC-SR04; a camera nao calcula coordenadas ou alcance do braco.

## 3. Preparar a garra real

Abra `arduino/mearm_calibrador/mearm_calibrador.ino` na IDE Arduino, mantendo
`backend_config.h` e `backend_protocol.h` na mesma pasta, com a biblioteca Servo.
O sketch do Freysta agora atende tanto o calibrador quanto CMD/ACK/EVT/ERR.
Nao use `mock.ino` para mover o braco. O firmware separado com `profiles.h`
foi substituido pela integracao no calibrador.

Os dados existentes sao reaproveitados nos mesmos enderecos da EEPROM:

| Dado do calibrador | Uso automatico |
| --- | --- |
| Ponto Y | Coleta P01 |
| Ponto X | Entrega E01 |
| Ponto neutro N | Retorno HOME e referencia logica inicial |
| LIM e GCALIB | Limites e abertura/fechamento dos mesmos servos |
| SPEED | Velocidade da sessao; padrao original ao reiniciar |
| SENSOR:ON/OFF | Configuracao de presenca do HC-SR04, preservada na EEPROM |

Confira e grave Y, X, N, limites e GCALIB no calibrador, teste as trajetorias e
o ciclo `RUN`, e envie `AUTO:VALIDAR` com o braco parado. Nao ha copia manual de
angulos para outro arquivo. A validacao nao move motores e registra uma assinatura
dos dados conferidos, nos bytes 96–99 do Uno. `AUTO:STATUS` consulta a liberacao;
`AUTO:INVALIDAR` remove somente a liberacao. Dados antigos incompletos ou fora
dos limites sao recusados para operacao automatica.

Salvar novamente pontos, limites ou GCALIB exige nova validacao. O backend e o
`RUN` compartilham as mesmas etapas, altura intermediaria 80/80 limitada pelos
limites, pausas e velocidade do ciclo original. Confirme o caminho entre pontos,
nao apenas as poses finais. A etapa tem timeout local de 25 s por padrao; mantenha
o timeout do backend maior. Consulte o [guia do firmware](../arduino/mearm_calibrador/README.md).

O boot nao energiza os servos. Depois de inspecionar/alinha-los, envie Reset pelo
painel antes de iniciar. Reset nao faz homing fisico. Stop/watchdog suspendem os
passos e mantem o ultimo comando dos servos; inspecione o estado antes de retomar.
Os eventos de garra indicam fim da trajetoria comandada, sem encoder ou sensor
de preensao; nao comprovam que o objeto foi segurado. Fonte e GND devem seguir a
montagem validada no [guia do calibrador](../arduino/mearm_calibrador/README.md).

## 4. Confirmar a chegada fisica

Em `arduino/mearm_calibrador/backend_config.h`, configure a lista
`INTELIESTEIRA_ARRIVAL_PINS`: a primeira entrada e R01, ate a decima para R10.
Ela inicializa `BACKEND_ARRIVAL_PINS`. `-1` significa nao instalado e bloqueia a rota.
Confirme a placa, os pinos disponiveis, a tensao e a polaridade dos sensores
ANTES de conecta-los. Nao usa o HC-SR04 do calibrador como comprovacao de destino.
Sensores nao podem compartilhar pinos entre si, com os servos, serial ou HC-SR04.

As entradas usam INPUT_PULLUP; ajuste `BACKEND_SENSOR_ACTIVE_LOW` ao sensor digital
validado. Configure apenas as saidas instaladas e teste cada uma. Para um teste
fisico de somente uma regiao, as duas saidas dessa regiao devem estar operantes,
pois o backend balanceia as unidades entre elas.

O backend arma o destino antes da coleta e inicia sua observacao apos START.
Sensor bloqueado ao armar/iniciar causa erro. Somente uma nova borda, apos nivel
livre estavel e com debounce durante transporte, emite
`EVT:ciclo:DESTINO_ALCANCADO:Rxx:SENSOR`. Reenvios nao repetem movimentos.
O receptor lembra oito IDs aposentados em RAM; reiniciar a placa perde esse
historico. Reset/retomada exigem inspecao do produto. Heartbeats ausentes por
quatro segundos interrompem a operacao. Parada de software nao substitui o
dispositivo de parada fisica da bancada.

## 5. Fazer o EV3 iniciar o receptor automaticamente

Copie os arquivos Python de `ev3/` para o EV3. Crie `token.txt` nessa pasta, com
uma chave aleatoria de 16 a 128 letras/numeros, `_` ou `-`. Guarde a mesma chave
em um arquivo local no PC, fora do Git. Nao envie a chave pelo painel.

Pelo SSH, confirme primeiro:

```sh
command -v pybricks-micropython
cd /home/robot/inteliEsteira/ev3
pybricks-micropython server.py
```

O caminho acima e um EXEMPLO. Confirme tambem o usuario e o ambiente
Pybricks 2.x/ev3dev do colaborador. Depois de verificar o receptor manualmente,
pare-o e adapte `ev3/inteliesteira.service.example` aos caminhos reais. O exemplo
usa systemd, usuario `robot` e executavel `/usr/bin/pybricks-micropython`.
O usuario deve ter acesso aos motores e ao arquivo token. Instale no proprio EV3:

```sh
sudo cp inteliesteira.service.example /etc/systemd/system/inteliesteira.service
sudo systemctl daemon-reload
sudo systemctl enable --now inteliesteira
systemctl status inteliesteira
journalctl -u inteliesteira -n 50
```

Execute o `cp` da pasta que contem o arquivo adaptado. Reinicie o EV3 e confirme
que o receptor volta a escutar em 8765, sem movimento automatico. Nao rode o
teste manual `main.py` junto com o servico, pois ambos usam os motores.
Para desativar: `sudo systemctl disable --now inteliesteira`.
Referencia: [servicos systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).

## 6. Operar o conjunto real pelo painel

Com IP, COM, perfis, HC-SR04 e retangulo de leitura E01 confirmados:

```powershell
.\scripts\iniciar-real.ps1 -Ev3Host <IP_REAL> -ArduinoPort <COM_REAL> `
  -TokenFile <ARQUIVO_LOCAL_DA_CHAVE> -PickupRoi <X,Y,LARGURA,ALTURA> -ProfilesCalibrated
```

Substitua os campos entre `<...>`; nao execute os marcadores literalmente. Use
aspas no valor de `-PickupRoi`; apesar do nome historico, delimita a leitura em E01.
O script inicia o Flask e a observacao automatica sem reloader. A conclusao
padrao vem do evento do controlador da esteira. `-RequirePhysicalArrival` exige
sensores adicionais de chegada no Arduino. Nao grava a placa, instala servicos ou calibra motores.
Feche o monitor serial e o calibrador para liberar a COM ao backend.

Abra http://127.0.0.1:5000. Aguarde a liberacao, apresente um cubo ao HC-SR04 em
P01 e acompanhe coleta, leitura, transporte e conclusao da unidade na fila. Confira a trajetoria e a saida esperada; depois
teste as duas saidas de cada regiao, parada durante movimento, etiqueta incorreta,
sensor bloqueado e perda de conexao. O proximo item so avanca apos conclusao.
O EV3 ainda precisa de verificacao das rotacoes, referencia inicial e retorno do
seletor; o servico nao corrige calibracao mecanica. A bancada virtual nao aprova
essas condicoes fisicas.

## Persistencia da aplicacao principal

`data/inteliesteira.json` recebe automaticamente todos os cadastros, alteracoes,
exclusoes e vinculos ArUco. A aplicacao carrega o arquivo ao abrir, sem operacao
manual. A bancada padrao usa o mesmo JSON. Para outra maquina, leve o projeto com
esse arquivo atualizado (copia ou commit/push e atualizacao na outra maquina).

`data/inteliesteira.db` e criado automaticamente e mantem fila, historico e uma
copia dos produtos para as referencias operacionais. Nao exige instalar banco.
O JSON transporta os cadastros; para migrar tambem o historico, use backup SQLite.
`data/catalogo-inicial.json` e apenas a carga inicial quando nao existem JSON nem
cadastros locais.

## Verificar o firmware sem gravar a placa

Com Arduino CLI, core `arduino:avr` e biblioteca Servo instalados:

```powershell
arduino-cli compile --fqbn arduino:avr:uno arduino/mearm_calibrador
```

Para executar o proprio sketch em um computador, com servos, relogio e EEPROM
simulados, informe um compilador C++17 (`g++`, `clang++` ou `zig`):

```powershell
.\.venv\Scripts\python.exe -m scripts.testar_firmware --compiler <CAMINHO_DO_COMPILADOR>
```

Os cenarios cobrem as etapas usando Y/X/N salvos, ACK antes de movimento, reenvios,
parada e reset durante movimento, watchdog, timeout, ordem/ciclo incorretos,
invalidacao e corrupcao da calibracao, recarga da EEPROM, presenca HC-SR04,
comandos manuais, overflow serial e bordas dos sensores de destino. O host usa
registros EEPROM tipados porque `int` tem tamanho diferente no PC e no AVR;
o layout AVR original e verificado por `static_assert` na compilacao do Uno.
Esses testes nao verificam alcance, corrente, preensao ou colisoes reais.
