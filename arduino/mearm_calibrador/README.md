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
da EEPROM. A rotina `RUN` e o backend compartilham as mesmas etapas de movimento,
com a altura intermediária 80/80, velocidades e pausas do ciclo original.
Essas trajetórias precisam estar livres na montagem real.

## Liberar a calibração para o automático

1. Confira os limites, a abertura/fechamento e os pontos Y (P01), X (E01) e N.
   Grave-os pelos comandos do calibrador; os registros de limites e N devem existir.
2. Teste os pontos e o ciclo `RUN` na bancada. Os valores de fábrica não comprovam
   que a montagem está calibrada.
3. Com o braço parado, envie `AUTO:VALIDAR`. Esse comando não movimenta motores:
   registra a conferência dos valores existentes e responde se foram aceitos.
4. `AUTO:STATUS` consulta a liberação; `AUTO:INVALIDAR` a remove sem apagar pontos.
5. Feche o calibrador/monitor serial, inicie o backend com os perfis habilitados,
   conecte os dispositivos e use **Resetar** antes de iniciar a fila.

A liberação fica nos bytes 96–99 do Uno, sem alterar os registros antigos.
Salvar Y/X/N, limites ou GCALIB invalida a liberação. Dados corrompidos ou
incompletos também bloqueiam o automático; não são aceitos por terem sido
limitados pelo carregador manual. Os dados e a liberação persistem após reiniciar.
Não formate a EEPROM ao gravar o firmware se quiser preservar as calibrações.

O boot mantém os servos desligados e usa N como referência lógica. Alinhe o
braço fisicamente antes do primeiro movimento. Reset não faz homing.

## Comandos do fluxo

| Comando após `CMD:<ciclo>:` | Ação e confirmação |
| --- | --- |
| `SISTEMA:PING` | ACK de comunicação, sem movimento |
| `GARRA:AREA:P01` | Seleciona a coleta Y, sem movimento |
| `GARRA:PEGAR` | Coleta em Y e levanta; EVT `GARRA_COLETA_CONCLUIDA` |
| `GARRA:POSICIONAR:E01` | Move até X segurando; EVT `GARRA_POSICIONAMENTO_CONCLUIDO` |
| `GARRA:SOLTAR` | Abre e afasta de X; EVT `GARRA_ENTREGA_CONCLUIDA` |
| `GARRA:HOME` | Retorna a N; EVT `GARRA_HOME_CONCLUIDO` |
| `GARRA:STOP` | Interrompe os passos mantendo os últimos pulsos |
| `SISTEMA:RESET` | Limpa a operação lógica, sem movimentar |

O ACK é enviado antes do movimento; EVT sai apenas ao terminar a etapa.
Durante `moverSuave` a leitura serial continua atendendo PING, repetição e STOP.
Reenvios de uma etapa em andamento não executam outro movimento; após conclusão
repetem ACK/EVT. Eventos confirmam trajetória comandada, sem encoder/preensão.
Oito IDs encerrados ficam em RAM; reiniciar a placa perde esse histórico.

O backend tem posse exclusiva até encerrar o ciclo: comandos manuais de movimento
ou calibração ficam bloqueados nesse intervalo. `STOP/FREE` manuais mantêm o
comportamento original de soltar servos. O STOP do backend e seu watchdog mantêm
os últimos pulsos; reset durante movimento interrompe e exige novo reset parado.
Perda de mensagens por 4 s ou etapa acima de 25 s interrompem a operação.
O adaptador serial do backend envia PING a cada segundo também nos ciclos
individuais da API, durante a espera pela conclusão de um movimento.

## Sensores

A operacao automatica habilita o HC-SR04 com `CMD:PRESENCA:PRESENCA:CONFIGURAR:10:3000`.
O firmware confirma por ACK e emite `SENSOR:PRESENTE:<cm>` / `SENSOR:AUSENTE:<cm>`.
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
