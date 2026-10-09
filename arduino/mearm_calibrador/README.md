# Firmware do calibrador MeArm

Este sketch controla o MeArm com quatro servos e oferece calibração manual pela interface web de bancada. O HC-SR04 é opcional e permanece desativado até ser habilitado pela interface.

## Pinos

- Base: D10
- Ombro: D11
- Cotovelo: D6
- Garra: D3
- HC-SR04 (opcional): TRIG D8, ECHO D9
- Serial: 9600 baud

Use uma fonte externa adequada para os servos e ligue o GND da fonte ao GND do Arduino. Não alimente os servos pelo pino 5 V do Arduino.

## Escopo e compatibilidade

Este é o firmware de calibração manual usado com a página RoboArm Controller. Ele usa comandos de texto próprios, como `POSE`, `SPEED`, `LIM` e `RUN`. O firmware de bancada `arduino/mock.ino` e o adaptador serial da aplicação principal usam frames `CMD/ACK/EVT/ERR`; portanto, este sketch ainda não substitui o firmware de produção nem fala diretamente com o fluxo principal da aplicação.

Os limites e posições iniciais são valores para calibração de bancada. Confirme os limites físicos de cada eixo com movimentos curtos e mantenha a mão no botão de parada/desconexão durante os testes.
