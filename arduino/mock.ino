/*
 * Firmware de bancada: protocolo e eventos simulados, SEM pinos ou motores.
 * P01 (coleta) e E01 (entrega) sao perfis logicos; nao ha coordenadas inventadas.
 * Para hardware real, implementar movimentos nao bloqueantes, limites e sensores.
 * O evento de chegada desta bancada e SIMULADO, nunca SENSOR.
 */
const unsigned long SERIAL_BAUDRATE = 9600;
String currentCycle = "";
String destination = "";
String sensorDestination = "";
String retiredCycles[8];
byte retiredCursor = 0;
unsigned int acceptedStages = 0;
unsigned long lastValidMessage = 0;
bool operationActive = false;

void sendMessage(const String &kind, const String &cycle, const String &payload) {
  Serial.print(kind); Serial.print(':'); Serial.print(cycle); Serial.print(':'); Serial.println(payload);
}
void ack(const String &cycle, const String &command) { sendMessage("ACK", cycle, command); }
void error(const String &cycle, const String &command, const String &code) { sendMessage("ERR", cycle, command + ':' + code); }
bool validDestination(const String &value) {
  if (value.length() != 3 || value[0] != 'R' || !isDigit(value[1]) || !isDigit(value[2])) return false;
  int number = value.substring(1).toInt(); return number >= 1 && number <= 10;
}
void retireCurrent() {
  if (currentCycle.length()) { retiredCycles[retiredCursor] = currentCycle; retiredCursor = (retiredCursor + 1) % 8; }
  currentCycle = ""; acceptedStages = 0; operationActive = false; destination = ""; sensorDestination = "";
}
bool beginCycle(const String &cycle) {
  if (currentCycle == cycle) return true;
  for (byte index = 0; index < 8; index++) if (retiredCycles[index] == cycle) return false;
  if (operationActive) return false;
  retireCurrent(); currentCycle = cycle; return true;
}
void completion(const String &cycle, const String &command) {
  if (command == "GARRA:PEGAR") sendMessage("EVT", cycle, "GARRA_COLETA_CONCLUIDA");
  else if (command == "GARRA:POSICIONAR:E01") sendMessage("EVT", cycle, "GARRA_POSICIONAMENTO_CONCLUIDO");
  else if (command == "GARRA:SOLTAR") sendMessage("EVT", cycle, "GARRA_ENTREGA_CONCLUIDA");
  else if (command == "GARRA:HOME") sendMessage("EVT", cycle, "GARRA_HOME_CONCLUIDO");
  else if (command == "ESTEIRA:START") sendMessage("EVT", cycle, "DESTINO_ALCANCADO:" + destination + ":SIMULADO");
  else if (command.startsWith("SENSOR:INICIAR:")) sendMessage("EVT", cycle, "DESTINO_ALCANCADO:" + command.substring(15) + ":SIMULADO");
}
void processCommand(String frame) {
  int first = frame.indexOf(':'); int second = frame.indexOf(':', first + 1);
  if (first < 0 || second < 0) { sendMessage("ERR", "SEM_CICLO", "FRAME_MALFORMADO"); return; }
  String kind = frame.substring(0, first), cycle = frame.substring(first + 1, second), command = frame.substring(second + 1);
  kind.trim(); cycle.trim(); command.trim(); kind.toUpperCase(); command.toUpperCase();
  if (kind != "CMD" || cycle.length() == 0 || cycle.length() > 32) { error("SEM_CICLO", command, "FRAME_INVALIDO"); return; }
  for (unsigned int index = 0; index < cycle.length(); index++) {
    char character = cycle[index];
    if (!isAlphaNumeric(character) && character != '_' && character != '-') { error("SEM_CICLO", command, "CICLO_INVALIDO"); return; }
  }
  lastValidMessage = millis();
  // PING nao interfere no cache da operacao em andamento.
  if (command == "SISTEMA:PING") { ack(cycle, command); return; }
  if (command == "ESTEIRA:STOP" || command == "GARRA:STOP" || command == "SISTEMA:RESET") {
    retireCurrent(); ack(cycle, command); return;
  }
  if (command == "SENSOR:DESARMAR") { retireCurrent(); ack(cycle, command); return; }
  unsigned int stage = 0;
  if (command == "GARRA:AREA:P01") stage = 1;
  else if (command == "GARRA:PEGAR") stage = 2;
  else if (command == "GARRA:POSICIONAR:E01") stage = 4;
  else if (command == "GARRA:SOLTAR") stage = 8;
  else if (command == "GARRA:HOME") stage = 16;
  else if (command.startsWith("DESTINO:") && validDestination(command.substring(8))) stage = 32;
  else if (command == "ESTEIRA:START") stage = 64;
  else if (command.startsWith("SENSOR:ARMAR:") && validDestination(command.substring(13))) stage = 128;
  else if (command.startsWith("SENSOR:INICIAR:") && validDestination(command.substring(15))) stage = 256;
  if (!stage) { error(cycle, command, "COMANDO_DESCONHECIDO"); return; }
  if (!beginCycle(cycle)) { error(cycle, command, "CICLO_OCUPADO_OU_INTERROMPIDO"); return; }
  if (stage == 32) {
    String selected = command.substring(8);
    if (destination.length() && destination != selected) { error(cycle, command, "DESTINO_BLOQUEADO"); return; }
    destination = selected;
  }
  if (stage == 64 && !destination.length()) { error(cycle, command, "DESTINO_NAO_CONFIGURADO"); return; }
  if (stage == 2 && !(acceptedStages & 1)) { error(cycle, command, "AREA_NAO_CONFIGURADA"); return; }
  if (stage == 4 && !(acceptedStages & 2)) { error(cycle, command, "COLETA_NAO_CONFIRMADA"); return; }
  if (stage == 8 && !(acceptedStages & 4)) { error(cycle, command, "ENTREGA_NAO_POSICIONADA"); return; }
  if (stage == 128) sensorDestination = command.substring(13);
  if (stage == 256 && sensorDestination != command.substring(15)) { error(cycle, command, "SENSOR_NAO_ARMADO"); return; }
  // Aqui apenas validamos e simulamos. Firmware fisico deve emitir EVT ao terminar a acao.
  if (!(acceptedStages & stage)) acceptedStages |= stage;
  operationActive = true;
  ack(cycle, command); completion(cycle, command);
}
void setup() { Serial.begin(SERIAL_BAUDRATE); Serial.setTimeout(50); }
void loop() {
  if (operationActive && millis() - lastValidMessage > 4000) retireCurrent();
  if (!Serial.available()) return;
  String frame = Serial.readStringUntil('\n'); frame.trim();
  if (frame.length() && frame.length() <= 160) processCommand(frame);
}
