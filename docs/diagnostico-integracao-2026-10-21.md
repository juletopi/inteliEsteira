# Revisão da integração — 21/10/2026

## Resultado

Os componentes compartilham um protocolo de operação, mas a calibração web e o
automático ainda executam trajetórias diferentes. Detectar um marcador no monitor
da câmera não autoriza transporte: somente um ciclo iniciado pelo HC-SR04 chega
ao comando do EV3. Os testes de software não comprovam o posicionamento físico
do cubo nem qual versão está gravada nos dispositivos.

## Diálogo esperado

| Etapa | Comunicação | Condição para avançar |
| --- | --- | --- |
| Preparar | PC → Arduino e EV3: `SISTEMA:PING`, `SISTEMA:RESET` | Ambos respondem `ACK` |
| Preparar a garra | PC → Arduino: `SISTEMA:STATUS` | Reset concluído, EEPROM validada e neutro sincronizado |
| Armar presença | PC → Arduino: `PRESENCA:CONFIGURAR:<cm>:<ms>` | `ACK`; leitura anterior limpa e novo evento do sensor |
| Detectar | Arduino → PC: `SENSOR:PRESENTE:<cm>` | Fluxo ativo e confirmação nova |
| Coletar | PC → Arduino: `GARRA:PERFIL`, `GARRA:AREA:P01`, depois um `GARRA:PASSO:P` por posição | `ACK` e `EVT:...:GARRA_PASSO_CONCLUIDO:P:<n>` em cada passo |
| Entregar | PC → Arduino: um `GARRA:PASSO:E` por posição | `ACK` e `EVT:...:GARRA_PASSO_CONCLUIDO:E:<n>` em cada passo; último passo termina no neutro |
| Identificar | PC lê câmera após a entrega e o retorno | ArUco cadastrado dentro do prazo de 8 s |
| Transportar | PC → EV3: `DESTINO:Rxx`, `ESTEIRA:START` | `ACK` em cada comando |
| Concluir | EV3 → PC: `EVT:<ciclo>:DESTINO_ALCANCADO:Rxx` | Destino e identificador de ciclo correspondem |

Os comandos usam `CMD:<ciclo>:<comando>` e respostas `ACK`, `ERR` ou `EVT`.
O mesmo identificador acompanha Arduino, câmera, banco e EV3 durante a unidade.
O HC-SR04 usa eventos sem identificador de ciclo; o PC cria o ciclo quando aceita
a presença. O EV3 autentica com `AUTH`/`READY` antes do protocolo operacional.
`ACK` confirma aceitação; o aplicativo aguarda `EVT` para concluir movimento.

## Evidências da bancada

- Ciclo `c53532e699b2`: firmware recusou `GARRA:AREA:P01` com
  `CALIBRATION_NOT_VALIDATED`. O indicador de perfil calibrado no PC não substitui
  a validação da EEPROM feita por `AUTO:VALIDAR` no Arduino.
- Ciclo `479ac9101552`: terminou coleta, posicionamento, soltura e retorno da garra.
  Depois expirou a busca por ArUco em 8 segundos. O código interrompeu antes de
  `DESTINO`/`ESTEIRA:START`, conforme a ordem implementada.
- A observação posterior identificou `PROD-SUL-01`, PR, destino calculado R03,
  enquanto o fluxo estava parado. Essa observação não retoma o ciclo que falhou.
- Na consulta de conexão realizada durante esta revisão, o EV3
  `192.168.137.3:8765` não respondeu no prazo. O automático exige os dois
  controladores disponíveis antes de movimentar a garra.
- O painel ainda mostrava presença de 3 cm com o Arduino desconectado. Tratava-se
  do último evento armazenado, não de uma nova leitura.
- Ao retomar a revisão em 21/10, a aplicação local na porta 5000 estava desligada.

## Falhas corrigidas no código local

1. **Rearme do sensor:** o PC limpa seu estado de presença ao reconfigurar o
   HC-SR04. Antes, uma nova mensagem `PRESENTE` podia ser ignorada porque a leitura
   antiga também era `PRESENTE`. O mock antigo escondia essa diferença ao limpar
   o estado do PC por conta própria.
2. **USB desconectado:** o estado do sensor passa a desconhecido em desconexão ou
   falha serial. O painel não apresenta a leitura anterior como presença atual.
3. **Diagnóstico:** eventos do HC-SR04 entram no histórico, com horário. Pings
   continuam atualizando a saúde da conexão, mas não expulsam os eventos de
   operação do histórico limitado. A API expõe a última falha de leitura.
4. **Controle da operação:** o Dashboard oferece iniciar, parar e resetar; mostra
   o estado do fluxo mesmo quando o controlador geral está `IDLE`.
5. **Liberação do calibrador:** a página aguarda a confirmação de fechamento da
   porta USB pelo iframe antes de apresentar a sessão como encerrada. Antes,
   liberava a sessão no backend enquanto o navegador ainda fechava a porta.
6. **Servidor EV3:** erros reais de socket são tratados como falha de conexão;
   somente timeout normal continua o polling. Antes, qualquer `OSError` era
   tratado como timeout e adiava a reação à desconexão.
7. **Configuração dos testes:** valores explicitamente fornecidos à aplicação
   têm precedência sobre as configurações salvas da bancada. Isso evita que um
   teste com controladores virtuais herde os dispositivos reais do usuário.

O ajuste do servidor EV3 está no arquivo local `ev3/server.py`; ele não foi
instalado no bloco durante esta revisão.

## Alinhamento implementado após a revisão inicial

### Trajetória

O calibrador pode exportar o fluxo atual para a aplicação ao usar **Salvar fluxo
e encerrar**. A página salva o perfil localmente, valida os ângulos e pausas,
preserva o arquivo anterior se a nova gravação falhar e libera a porta serial
somente após confirmação do iframe.

No ciclo coletivo, o PC manda o número de passos e a suavidade, depois envia cada
pose do CSV em ordem. O Arduino compara cada pose com os limites salvos e só
responde `GARRA_PASSO_CONCLUIDO` após terminar `moverSuave` e a pausa daquele
passo. O perfil versionado fica no computador; não é gravado na EEPROM do
Arduino. A trajetória atual incluída no repositório corresponde ao CSV oficial
de 16/10/2026: quatro passos para pegar, quatro para entregar, 24 ms/grau e
pausas de 300 ms.

### Referência e liberação do automático

O backend consulta `SISTEMA:STATUS` e interrompe a preparação se faltar reset,
validação EEPROM ou referência neutra. `AUTO:VALIDAR` continua validando os
registros Y/X/N, limites e abertura/fechamento antigos da EEPROM; o CSV dinâmico
fica separado em um JSON local versionado. O botão **Confirmar braço no neutro**
envia `SISTEMA:SYNC` e o firmware aceita apenas os ângulos neutros salvos, com
todos os servos soltos. A confirmação não move o braço.

Assim, ainda é obrigatório validar a EEPROM no calibrador mesmo com o perfil
CSV carregado. Alterar Y/X/N, limites ou GCALIB invalida a validação e exige
`AUTO:VALIDAR` novamente.

### Limites de evidência

O firmware atualizado está no repositório, mas não foi compilado com toolchain
Arduino nesta sessão nem gravado no Arduino físico. A validação de EEPROM e a
confirmação de pose só podem ser comprovadas na placa. Também não foi feito um
ciclo físico completo com o EV3.

### Cubo colocado durante movimento

O firmware pausa `monitorarSensor` durante `cicloEmExecucao`. O workflow também
descarta as bordas ocorridas durante o transporte ao atualizar seu cursor no fim
do ciclo. Não há uma fila física de presença equivalente ao comportamento do
calibrador web. Suportar esse caso exige reconciliar uma leitura nova após o
retorno, preservando a proteção contra pegar duas vezes o mesmo cubo.

### Câmera e falha de leitura

O detector e a ROI são os mesmos na observação e no ciclo. O ciclo tenta ler
somente após a entrega e falha após o prazo. Não existe retomada somente da
leitura/transporte de um cubo já depositado. Reset seguido de novo fluxo inicia
uma nova coleta; ele não continua automaticamente a unidade anterior.

## Verificação

Resultado anterior: 191 testes de `python -m unittest discover -s tests -q`
passaram. Após o alinhamento de trajetória, os três testes do contrato de
integração passaram com firmware serial simulado. As páginas Dashboard,
Calibração e calibrador responderam HTTP 200; os três scripts renderizados
passaram pela verificação de sintaxe do Node.js.
As páginas Dashboard, Calibração e calibrador responderam HTTP 200; os três
scripts renderizados passaram pela verificação de sintaxe do Node.js.

A aplicação foi iniciada em `http://127.0.0.1:5000` com `AUTO_OPERATION=0`.
Na consulta final, o fluxo estava parado, Arduino/EV3/câmera desconectados e
presença desconhecida (sem exibir a leitura antiga de 3 cm). Nenhum ciclo físico
foi iniciado. O início automático foi desativado apenas no ambiente desse
processo; o arquivo de configurações da bancada foi preservado.

`tests/test_integration_contract.py` exercita parsing serial, workflow, detector
OpenCV com imagem ArUco gerada e ponte TCP do EV3 com motores virtuais:

- presença nova após leitura antiga → trajetória oficial de quatro mais quatro
  passos → ArUco → R03 →
  `ESTEIRA:START` com o mesmo identificador de ciclo;
- câmera sem marcador → garra concluída e esteira bloqueada por `ARUCO_NOT_FOUND`;
- leitura isolada da câmera → identificação sem comando de movimento.

Esses testes validam a integração de software com respostas simuladas da garra.
Não executam o sketch em um Arduino real e não validam servo, garra, alinhamento,
detecção física do sensor ou o código atualmente instalado no EV3.

## Correções do fluxo coletivo (21/10, noite)

- **EV3:** a porta 8765 recusava conexão (ping respondia): a ponte `server.py`
  não estava rodando no bloco. `scripts/instalar-ev3.ps1` copia `ev3/` e inicia
  a ponte (pede a senha SSH do EV3); `-Servico` instala o systemd para subir no boot.
- **Heartbeat:** um único PING acima de 0,5 s (Wi-Fi do EV3, CPU ocupada pela
  câmera) encerrava o fluxo com `HEARTBEAT_FAILED`. Agora usa `COMMAND_TIMEOUT`
  e só interrompe após 3 falhas seguidas ou conexão perdida.
- **Re-sync da garra:** após parada durante movimento o firmware exige novo
  `SYNC`, que exige servos soltos — e não havia comando do backend para soltá-los.
  Novo `SISTEMA:LIBERAR` (firmware, API `POST /api/system/release-servos` e botão
  **Soltar servos** no Dashboard).
- **RAM do firmware:** 1535 → 769 bytes estáticos (literais de comando na flash,
  histórico de ciclos 8→4, buffers de passo 96→40). Antes sobravam ~500 bytes de
  pilha para o caminho aninhado `PASSO → moverSuave → verificarParadaCiclo`.
  Layout da EEPROM inalterado: `AUTO:VALIDAR` continua válido. Gravar com
  `scripts/gravar-firmware.ps1` (backend parado).
- **Simulador serial:** respondia só ACK, sem EVT, a `SISTEMA:STATUS` repetido com
  id fixo (`FW_STATUS`), quebrando a bancada. Testes atualizados para o fluxo por
  perfil: 192 testes Python e 20 cenários nativos do sketch passam.

## Operação automática ponta a ponta

- `AUTO_SYNC_NEUTRAL` (em `data/system_config.local.json`): a preparação confirma o
  neutro salvo sem clique (`SISTEMA:SYNC`; se os servos estiverem energizados após uma
  parada, `SISTEMA:LIBERAR` antes). O braço deve ficar no neutro entre ciclos; fora dele,
  salta para o neutro ao energizar no primeiro movimento.
- Dispositivo sem resposta **sem unidade em andamento** → o fluxo volta a
  `AGUARDANDO_CONEXAO`, reconecta, reseta e rearma sozinho. Durante uma unidade a falha
  continua parando em `ERRO` (o cubo pode estar no braço ou na esteira).
- No boot do backend, uma parada limpa (`PARADO`) não impede o rearme; `ERRO` e
  `INTERROMPIDO` ainda exigem o operador.
- `scripts/instalar-inicializacao.ps1` cria o atalho que roda `scripts/iniciar-backend.ps1`
  ao entrar no Windows (`-Remover` desfaz). `scripts/instalar-ev3.ps1` instala o serviço
  `inteliesteira` no EV3 e cadastra a chave SSH do PC.

## HC-SR04 e validação final

Medição direta no Uno com a área vazia: mediana **9 cm** estável; limite do perfil era
10 cm, então o fundo contava como cubo e o estado nunca voltava a `AUSENTE` (fluxo preso
até reiniciar). Limite passa a 5 cm (cubo lê 3–4 cm); firmware usa mediana de 5 leituras,
histerese de 2 cm, relata `SENSOR:DISTANCIA` a cada 1 s e atende `PRESENCA:LEITURA`.
O backend rearma o sensor ao fim de cada ciclo e avisa quando o fundo está dentro do limite.

Bancada após a correção: 9 ciclos `FINALIZADO` (R01, R02, R03, R07, R08, R09), sem
detecção falsa. Falhas restantes foram físicas/cadastro: garra fechando fora do cubo
(`ARUCO_NOT_FOUND` com o cubo ainda no sensor) e marcadores sem cadastro
(`ARUCO_NOT_REGISTERED`). Operação: `docs/operacao-automatica.md`.
