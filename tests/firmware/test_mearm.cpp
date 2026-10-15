#include "Arduino.h"
#include <iostream>
#include <stdexcept>
// Inclui o sketch de producao: os testes nao reimplementam a maquina de estados.
#define INTELIESTEIRA_ARRIVAL_PINS {2, -1, -1, -1, -1, -1, -1, -1, -1, -1}
#include "../../arduino/mearm_calibrador/mearm_calibrador.ino"

void check(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
size_t count(const std::string &text) {
  size_t n = 0, start = 0;
  while ((start = Serial.output.find(text, start)) != std::string::npos) { ++n; start += text.size(); }
  return n;
}
size_t writes() {
  return std::count_if(hostEvents.begin(), hostEvents.end(), [](const std::string &s) { return s.rfind("SERVO:", 0) == 0; });
}
void heartbeat() {
  static uint32_t last = 0;
  if (hostMillis - last >= 900) { last = hostMillis; Serial.feed("CMD:HEARTBEAT:SISTEMA:PING\n"); }
}
void fixture() {
  setup();
  // Usa os setters originais para criar os registros, em vez de outro catalogo.
  angB = 130; angBraco = 95; angCotovelo = 90; angG = 150; salvarPontoY();
  angB = 35; angBraco = 100; angCotovelo = 92; angG = 150; salvarPontoX();
  angB = 88; angBraco = 83; angCotovelo = 84; angG = 149; salvarPontoNeutro();
  salvarLimites(); salvarGarraCalib(150, 87);
  processarComando("AUTO:VALIDAR");
  check(backendCalibracaoValida(), "calibracao original nao foi validada");
  processarComando("CMD:DIAG:SISTEMA:RESET");
  hostOnDelay = heartbeat;
  Serial.clear();
}
void area() { processarComando("CMD:unit_1:GARRA:AREA:P01"); }
void pickup() { processarComando("CMD:unit_1:GARRA:PEGAR"); }
void fullCycle() {
  area(); pickup();
  check(angB == pontoY.base && angBraco == constrain(80, minBraco, maxBraco) && angCotovelo == constrain(80, minCotovelo, maxCotovelo) && angG == angGarraFechada, "coleta nao usou Y/GCALIB");
  processarComando("CMD:unit_1:GARRA:POSICIONAR:E01");
  check(angB == pontoX.base && angBraco == pontoX.braco && angCotovelo == pontoX.cotovelo && angG == angGarraFechada, "entrega nao usou X/GCALIB");
  processarComando("CMD:unit_1:GARRA:SOLTAR");
  check(angB == pontoX.base && angG == angGarraAberta, "soltura nao usou abertura calibrada");
  processarComando("CMD:unit_1:GARRA:HOME");
}
int main(int argc, char **argv) {
  try {
    check(argc == 2, "informe o cenario");
    std::string scenario = argv[1];
    if (scenario == "unvalidated") {
      setup(); processarComando("CMD:d:SISTEMA:RESET"); area();
      check(count("CALIBRATION_NOT_VALIDATED") == 1 && writes() == 0, "EEPROM vazia liberou movimento");
    } else {
      fixture();
      if (scenario == "cycle") {
        fullCycle();
        check(backendCompleted == 15, "etapas nao concluiram");
        check(angB == pontoNeutro.base && angBraco == pontoNeutro.braco && angCotovelo == pontoNeutro.cotovelo && angG == pontoNeutro.garra, "HOME nao usou N salvo");
        check(count("EVT:unit_1:GARRA_") == 4, "faltam eventos das etapas");
        auto ack = std::find(hostEvents.begin(), hostEvents.end(), "ACK:unit_1:GARRA:PEGAR");
        auto servo = std::find_if(hostEvents.begin(), hostEvents.end(), [](const std::string &s) { return s.rfind("SERVO:", 0) == 0; });
        check(ack < servo, "movimento antes do ACK");
      } else if (scenario == "retry") {
        area(); bool injected = false;
        hostOnDelay = [&]() { heartbeat(); if (!injected) { injected = true; Serial.feed("CMD:unit_1:GARRA:PEGAR\n"); } };
        pickup(); size_t before = writes(); pickup();
        check(writes() == before, "reenvio repetiu movimento");
        check(count("ACK:unit_1:GARRA:PEGAR") == 3 && count("EVT:unit_1:GARRA_COLETA_CONCLUIDA") == 2, "reenvio nao repetiu ACK/EVT corretamente");
      } else if (scenario == "stop" || scenario == "reset_moving") {
        area(); bool injected = false;
        hostOnDelay = [&]() { if (!injected) { injected = true; Serial.feed(scenario == "stop" ? "CMD:unit_1:GARRA:STOP\n" : "CMD:d:SISTEMA:RESET\n"); } };
        pickup();
        check(backendNeedsReset && backendCompleted == 0 && count("GARRA_COLETA_CONCLUIDA") == 0, "parada/reset emitiu conclusao");
        size_t before = writes(); pickup();
        check(writes() == before && count("RESET_REQUIRED") > 0, "parada permitiu reinicio");
      } else if (scenario == "watchdog") {
        area(); hostOnDelay = nullptr; pickup();
        check(backendNeedsReset && count("COMMUNICATION_LOST") == 1 && count("GARRA_COLETA_CONCLUIDA") == 0, "watchdog nao interrompeu");
      } else if (scenario == "timeout") {
        area(); bool jumped = false;
        hostOnDelay = [&]() { if (!jumped) { hostMillis += 26000; jumped = true; } heartbeat(); };
        pickup();
        check(backendNeedsReset && count("MOTION_TIMEOUT") == 1 && count("GARRA_COLETA_CONCLUIDA") == 0, "timeout nao interrompeu");
      } else if (scenario == "order") {
        area(); processarComando("CMD:unit_1:GARRA:POSICIONAR:E01");
        check(count("INVALID_STAGE") == 1 && writes() == 0, "etapa fora da ordem movimentou");
        processarComando("CMD:another:GARRA:PEGAR");
        check(count("CYCLE_LOCKED") == 1 && writes() == 0, "ciclo concorrente movimentou");
      } else if (scenario == "invalidate") {
        salvarPontoY(); check(!backendCalibracaoValida(), "salvar Y manteve liberacao antiga");
        processarComando("AUTO:VALIDAR"); check(backendCalibracaoValida(), "revalidacao falhou");
        salvarGarraCalib(151, 88); check(!backendCalibracaoValida(), "GCALIB manteve liberacao antiga");
      } else if (scenario == "corrupt") {
        Ponto corrupt = pontoY; corrupt.braco = 500; EEPROM.put(2, corrupt);
        carregarMemoria(); // O manual limita, mas a ponte deve recusar os dados brutos.
        check(pontoY.braco == maxBraco && !backendCalibracaoValida(), "corrupcao foi aceita apos constrain");
        area(); check(writes() == 0 && count("CALIBRATION_NOT_VALIDATED") == 1, "corrupcao autorizou coleta");
      } else if (scenario == "persist") {
        processarComando("SENSOR:ON:12:4000");
        pontoY = {0, 0, 0, 0}; pontoX = {0, 0, 0, 0}; pontoNeutro = {0, 0, 0, 0};
        sensorEnabled = false; sensorDistanceCm = 0; sensorStableMs = 0;
        carregarMemoria(); carregarConfigSensor();
        check(pontoY.base == 130 && pontoX.base == 35 && pontoNeutro.base == 88 && angGarraFechada == 87, "posicoes/garra nao recarregaram da EEPROM");
        check(sensorEnabled && sensorDistanceCm == 12 && sensorStableMs == 4000 && backendCalibracaoValida(), "configuracao HC-SR04/liberacao nao persistiu");
      } else if (scenario == "presence") {
        processarComando("CMD:PRESENCA:PRESENCA:CONFIGURAR:12:3000"); hostEcho = 8 * 58;
        check(count("ACK:PRESENCA:PRESENCA:CONFIGURAR:12:3000") == 1, "configuracao HC-SR04 nao confirmada");
        processarComando("CMD:PRESENCA:PRESENCA:CONFIGURAR:101:3000");
        check(count("INVALID_SENSOR_CONFIG") == 1 && sensorDistanceCm == 12, "configuracao HC-SR04 invalida aceita");
        for (int i = 0; i < 55; ++i) { hostMillis += 60; monitorarSensor(); }
        check(sensorPresent && count("SENSOR:PRESENTE:8") == 1, "HC-SR04 nao detectou presenca estavel");
        check(writes() == 0 && !backendOcupado(), "presenca acionou braco sem autorizacao");
      } else if (scenario == "manual") {
        processarComando("POSE:92:84:85:148");
        check(count("[POSE_DONE]") == 1 && angB == 92, "POSE manual regrediu");
        area(); size_t before = writes(); processarComando("POSE:100:90:90:150"); processarComando("Y");
        check(writes() == before && pontoY.base == 130 && backendCalibracaoValida(), "manual alterou ciclo automatico");
      } else if (scenario == "overflow") {
        Serial.feed(std::string(110, 'x') + "POSE:20:90:90:100\nCMD:d:SISTEMA:PING\n"); loop();
        check(writes() == 0 && count("ACK:d:SISTEMA:PING") == 1, "cauda de overflow executada ou parser nao recuperou");
      } else if (scenario == "missing_sensor") {
        processarComando("CMD:unit_1:SENSOR:ARMAR:R02");
        check(count("SENSOR_NOT_CONFIGURED") == 1 && writes() == 0, "sensor ausente liberou transporte");
      } else if (scenario == "sensor_blocked") {
        hostPins[2] = LOW; processarComando("CMD:unit_1:SENSOR:ARMAR:R01");
        check(count("SENSOR_BLOCKED") == 1 && writes() == 0 && count(":SENSOR\n") == 0, "sensor bloqueado foi aceito");
      } else if (scenario == "sensor_arrival") {
        processarComando("CMD:unit_1:SENSOR:ARMAR:R01"); fullCycle();
        processarComando("CMD:unit_1:SENSOR:INICIAR:R01");
        check(count("ACK:unit_1:SENSOR:INICIAR:R01") == 1, "nao iniciou observacao");
        hostPins[4] = LOW; backendMonitorar(); hostMillis += 40; backendMonitorar();
        check(count("DESTINO_ALCANCADO") == 0, "pino de outra saida confirmou chegada");
        hostPins[2] = LOW; backendMonitorar(); hostMillis += 10; backendMonitorar();
        check(count("DESTINO_ALCANCADO") == 0, "sensor sem debounce confirmou chegada");
        hostMillis += 25; backendMonitorar();
        check(count("EVT:unit_1:DESTINO_ALCANCADO:R01:SENSOR") == 1, "borda nao confirmou saida correta");
        processarComando("CMD:unit_1:SENSOR:INICIAR:R01");
        check(count("EVT:unit_1:DESTINO_ALCANCADO:R01:SENSOR") == 2, "reenvio nao recuperou evento");
        processarComando("CMD:unit_1:SENSOR:DESARMAR");
        check(!backendOcupado(), "sensor nao encerrou posse do ciclo");
        area(); check(count("CYCLE_LOCKED") > 0, "ID encerrado foi reutilizado");
      } else if (scenario == "early_sensor") {
        processarComando("CMD:unit_1:SENSOR:ARMAR:R01"); fullCycle();
        hostPins[2] = LOW; backendMonitorar(); hostMillis += 40; backendMonitorar();
        processarComando("CMD:unit_1:SENSOR:INICIAR:R01");
        check(count("DESTINO_ALCANCADO") == 0 && count("SENSOR_BLOCKED") == 1, "borda anterior ao transporte confirmou chegada");
      } else throw std::runtime_error("cenario desconhecido");
    }
    std::cout << "OK: " << scenario << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL: " << error.what() << "\n" << Serial.output;
    return 1;
  }
}
