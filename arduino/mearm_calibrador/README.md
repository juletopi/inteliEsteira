# MeArm: calibrador e operação pelo backend

Este é o sketch do Freysta (`f9c8593`), estendido com o protocolo da aplicação.
O mesmo firmware atende o calibrador manual e o fluxo automático. Não é preciso
copiar ângulos para outro sketch nem substituir o layout existente da EEPROM.

## Pinos e alimentação

- Base: D10; ombro: D11; cotovelo: D6; garra: D3.
- HC-SR04 opcional: TRIG D8 e ECHO D9; configuração original preservada.
- Serial: 9600 baud, mensagens terminadas por nova linha.

Use fonte externa adequada para os servos e GND comum com o Arduino. Não alimente
os servos pelo pino 5 V da placa. Na IDE Arduino, abra `mearm_calibrador.ino` com
os dois headers desta pasta e instale a biblioteca Servo.

## O que foi preservado

Comandos `POSE`, `SPEED`, `LIM`, `GCALIB`, `Y`, `X`, `N`, `TESTY/TESTX/TESTN`,
`RUN`, controles dos eixos e configuração `SENSOR:ON/OFF` continuam disponíveis.
Os pontos Y, X e neutro, limites e abertura/fechamento usam os mesmos endereços
da EEPROM. O comando legado `RUN` continua usando os pontos Y/X/N e a trajetória
fixa do sketch. A operação coletiva usa o perfil de passos enviado pelo módulo
web, com validação independente de limites no firmware. Teste a trajetória
coletiva em bancada antes de colocar a peça e a esteira em operação.

## Liberar a calibração para o automático

1. Confira os limites, a abertura/fechamento e os pontos Y (P01), X (E01) e N.
   Grave-os pelos comandos do calibrador; os registros de limites e N devem existir.
2. Teste os pontos e o ciclo `RUN` na bancada. Os valores de fábrica não comprovam
   que a montagem está calibrada.
3. Com o braço parado, envie `AUTO:VALIDAR`. Esse comando não movimenta motores:
   registra a conferência dos valores existentes e responde se foram aceitos.
4. `AUTO:STATUS` consulta a liberação; `AUTO:INVALIDAR` a remove sem apagar pontos.
5. No calibrador web, use **Salvar fluxo e encerrar** para transferir os passos
   atuais ao perfil da operação coletiva e liberar a porta USB. O perfil oficial
   inicial usa quatro passos para pegar e quatro para entregar. O backend envia
   cada pose e aguarda a confirmação do Arduino antes de mandar a próxima.
6. Com os servos soltos, alinhe o braço fisicamente ao neutro salvo. Na página
   Dashboard, use **Confirmar braço no neutro**. Essa ação sincroniza a referência
   lógica, sem movimentar os servos.
7. Conecte os dispositivos e use **Resetar operação** antes de iniciar a fila.

A liberação fica nos bytes 96–99 do Uno, sem alterar os registros antigos.
Salvar Y/X/N, limites ou GCALIB invalida a liberação. Dados corrompidos ou
incompletos também bloqueiam o automático; não são aceitos por terem sido
limitados pelo carregador manual. Os dados e a liberação persistem após reiniciar.
Não formate a EEPROM ao gravar o firmware se quiser preservar as calibrações.

O boot mantém os servos desligados e usa N como referência lógica. Alinhe o
braço fisicamente antes do primeiro movimento. Reset não faz homing.

O calibrador web consulta `PoseRef` no comando `?`. Após cada boot, o firmware
responde `PoseRef:NAO` até o operador alinhar fisicamente o braço ao neutro,
mantendo os servos soltos, e confirmar a pose no painel. O comando
`SYNC:<base>:<ombro>:<cotovelo>:<garra>` só atualiza a referência lógica, sem
energizar ou mover os servos; ele é recusado se algum servo estiver conectado
ou se os ângulos não corresponderem ao ponto neutro salvo. Movimentos manuais
ficam bloqueados até essa confirmação. A resposta aceita é `[POSE_SYNCED] ...`.

## Comandos do fluxo

| Comando após `CMD:<ciclo>:` | Ação e confirmação |
| --- | --- |
| `SISTEMA:PING` | ACK de comunicação, sem movimento |
| `SISTEMA:STATUS` | Informa se ainda requer reset, se a EEPROM foi validada e se o neutro foi referenciado |
| `SISTEMA:SYNC:B:A:C:G` | Confirma a pose neutra exata, com os servos soltos; não movimenta |
| `GARRA:PERFIL:<pegar>:<entregar>:<ms/°>` | Inicia o perfil da unidade e define quantidades e suavidade |
| `GARRA:AREA:P01` | Seleciona a área de coleta, sem movimento |
| `GARRA:PASSO:P:<ordem>:B:A:C:G:<pausa>` | Executa um passo da coleta; EVT `GARRA_PASSO_CONCLUIDO:P:<ordem>` |
| `GARRA:PASSO:E:<ordem>:B:A:C:G:<pausa>` | Executa um passo da entrega; EVT `GARRA_PASSO_CONCLUIDO:E:<ordem>` |
| `GARRA:STOP` | Interrompe os passos mantendo os últimos pulsos |
| `SISTEMA:RESET` | Limpa a operação lógica, sem movimentar |

O backend consulta `SISTEMA:STATUS` antes de habilitar o ciclo. A operação só
avança depois de reset, calibração EEPROM validada por `AUTO:VALIDAR`, referência
neutra confirmada e os dois controladores conectados. O PC envia os passos do
perfil na ordem; o firmware verifica os limites salvos e recusa passos fora de
ordem. O ACK sai antes do movimento e o EVT só depois de cada passo. Durante
`moverSuave` a leitura serial continua atendendo PING, repetição e STOP. Reenvios
de um passo em andamento não iniciam outro movimento. Eventos confirmam a
trajetória comandada, sem encoder ou confirmação física de preensão. Oito IDs
encerrados ficam em RAM; reiniciar a placa perde esse histórico.

O backend tem posse exclusiva até encerrar o ciclo: comandos manuais de movimento
ou calibração ficam bloqueados nesse intervalo. `STOP/FREE` manuais mantêm o
comportamento original de soltar servos. O STOP do backend e seu watchdog mantêm
os últimos pulsos; reset durante movimento interrompe e exige novo reset parado.
Perda de mensagens por 4 s ou etapa acima de 25 s interrompem a operação.
O adaptador serial do backend envia PING a cada segundo também nos ciclos
individuais da API, durante a espera pela conclusão de um movimento.

## Sensores

A operação automática aplica a distância e estabilidade do perfil salvo, por
exemplo `CMD:PRESENCA:PRESENCA:CONFIGURAR:10:4000`. O firmware confirma por ACK
e emite `SENSOR:PRESENTE:<cm>` / `SENSOR:AUSENTE:<cm>`.
O backend usa essa presenca para coletar em P01 e le o ArUco somente apos a entrega em E01.

O HC-SR04 mantém a leitura e a configuração de presença do calibrador. Ele não
substitui a identificação ArUco nem mede chegada nas saídas da esteira.
`backend_config.h` define entradas digitais R01–R10, inicialmente `-1` (ausentes).
Configure somente pinos e sensores confirmados; pinos dos servos, serial e
HC-SR04 são reservados e conflitos são rejeitados.

O protocolo `SENSOR:ARMAR:Rxx`, `SENSOR:INICIAR:Rxx` e `SENSOR:DESARMAR` exige
sensor livre e uma nova borda com debounce durante transporte para gerar
`EVT:<ciclo>:DESTINO_ALCANCADO:Rxx:SENSOR`. Entrada ausente/bloqueada falha sem
autorizar a coleta. Esteira e seletor são comandados pelo EV3.

Veja o [guia de teste integrado](../../docs/teste-integrado.md) para a bancada
virtual, conexão real, serviço do EV3 e validação do conjunto físico.
