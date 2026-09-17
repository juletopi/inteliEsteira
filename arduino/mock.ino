/*
 * Firmware de bancada da InteliEsteira.
 *
 * Valida o protocolo serial sem acionar pinos, motores ou sensores. Ele pode
 * ser gravado no Arduino UNO antes de o time definir o mapa eletrico final.
 * Comandos repetidos pelo backend recebem ACK novamente e nao sao reaplicados.
 */

const unsigned long SERIAL_BAUDRATE = 9600;

String selectedDestination = "";
String lastCommandFrame = "";
String lastCommandPayload = "";

void sendMessage(const String &kind, const String &cycleId, const String &payload) {
  Serial.print(kind);
  Serial.print(':');
  Serial.print(cycleId);
  Serial.print(':');
  Serial.println(payload);
}

void sendAck(const String &cycleId, const String &payload) {
  sendMessage("ACK", cycleId, payload);
}

void sendError(const String &cycleId, const String &command, const String &code) {
  sendMessage("ERR", cycleId, command + ':' + code);
}

bool isValidDestination(const String &destination) {
  if (destination.length() != 3 || destination.charAt(0) != 'R') {
    return false;
  }
  int number = destination.substring(1).toInt();
  return number >= 1 && number <= 10;
}

bool isGripperCommand(const String &payload) {
  return payload == "GARRA:PEGAR" ||
         payload == "GARRA:SOLTAR" ||
         payload == "GARRA:HOME";
}

void processCommand(const String &frame) {
  int firstSeparator = frame.indexOf(':');
  int secondSeparator = frame.indexOf(':', firstSeparator + 1);
  if (firstSeparator < 0 || secondSeparator < 0) {
    sendMessage("ERR", "SEM_CICLO", "FRAME_MALFORMADO");
    return;
  }

  String kind = frame.substring(0, firstSeparator);
  String cycleId = frame.substring(firstSeparator + 1, secondSeparator);
  String payload = frame.substring(secondSeparator + 1);
  kind.trim();
  cycleId.trim();
  payload.trim();
  kind.toUpperCase();
  payload.toUpperCase();

  if (kind != "CMD" || cycleId.length() == 0 || payload.length() == 0) {
    sendMessage("ERR", cycleId.length() ? cycleId : "SEM_CICLO", "FRAME_INVALIDO");
    return;
  }

  // Retransmissoes do mesmo comando sao idempotentes.
  if (frame == lastCommandFrame) {
    sendAck(cycleId, lastCommandPayload);
    return;
  }

  if (isGripperCommand(payload)) {
    sendAck(cycleId, payload);
  } else if (payload.startsWith("DESTINO:")) {
    String destination = payload.substring(String("DESTINO:").length());
    if (!isValidDestination(destination)) {
      sendError(cycleId, payload, "DESTINO_INVALIDO");
      return;
    }
    selectedDestination = destination;
    sendAck(cycleId, payload);
  } else if (payload == "ESTEIRA:START") {
    if (selectedDestination.length() == 0) {
      sendError(cycleId, payload, "DESTINO_NAO_CONFIGURADO");
      return;
    }
    sendAck(cycleId, payload);
    sendMessage("EVT", cycleId, "DESTINO_ALCANCADO:" + selectedDestination);
  } else if (payload == "ESTEIRA:STOP") {
    sendAck(cycleId, payload);
  } else if (payload == "SISTEMA:RESET") {
    selectedDestination = "";
    sendAck(cycleId, payload);
  } else {
    sendError(cycleId, payload, "COMANDO_DESCONHECIDO");
    return;
  }

  lastCommandFrame = frame;
  lastCommandPayload = payload;
}

void setup() {
  Serial.begin(SERIAL_BAUDRATE);
  Serial.setTimeout(50);
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String frame = Serial.readStringUntil('\n');
  frame.trim();
  if (frame.length() > 0) {
    processCommand(frame);
  }
}
