#pragma once

// Ponte cooperativa CMD/ACK/EVT/ERR. Movimentos e calibracao pertencem ao sketch.
// Os registros originais da EEPROM (0..78 no Uno) nao mudam de endereco/layout.
const int EEPROM_BACKEND_ADDR = 96;
const uint16_t EEPROM_BACKEND_MAGIC = 0xB4E1;
// Uno tem 2 KB de RAM: historico curto e passo guardado no tamanho maximo do comando.
const byte BACKEND_RETIRED = 4;
char backendCycle[33] = "", backendRetired[BACKEND_RETIRED][33] = {};
byte backendRetiredIndex = 0, backendCompleted = 0;
int backendAction = -1, backendDestination = -1;
bool backendNeedsReset = true, backendArea = false;
bool backendSensorStarted = false, backendSensorDone = false;
bool backendSensorRaw = false, backendSensorStable = false, backendSensorClear = false;
unsigned long backendLastValid = 0, backendActionStarted = 0, backendSensorChanged = 0;
bool backendProfileReady = false;
byte backendPickupCount = 0, backendDeliveryCount = 0, backendPickupNext = 1, backendDeliveryNext = 1;
byte backendSpeedMs = 24;
// "GARRA:PASSO:P:20:180:180:180:180:10000" tem 38 caracteres.
char backendStepActive[40] = "", backendStepLast[40] = "";

bool backendIs(const char *value, const __FlashStringHelper *expected) {
  const char *flash = reinterpret_cast<const char *>(expected);
  for (size_t i = 0; ; ++i) {
    char c = pgm_read_byte(flash + i);
    if (value[i] != c) return false;
    if (!c) return true;
  }
}
const __FlashStringHelper *backendCommand(byte action) {
  switch (action) {
    case 0: return F("GARRA:PEGAR");
    case 1: return F("GARRA:POSICIONAR:E01");
    case 2: return F("GARRA:SOLTAR");
    default: return F("GARRA:HOME");
  }
}
const __FlashStringHelper *backendEvent(byte action) {
  switch (action) {
    case 0: return F("GARRA_COLETA_CONCLUIDA");
    case 1: return F("GARRA_POSICIONAMENTO_CONCLUIDO");
    case 2: return F("GARRA_ENTREGA_CONCLUIDA");
    default: return F("GARRA_HOME_CONCLUIDO");
  }
}
void backendPrefix(const __FlashStringHelper *kind, const char *cycle) {
  Serial.print(kind); Serial.print(':'); Serial.print(cycle); Serial.print(':');
}
void backendAck(const char *cycle, const char *command) {
  backendPrefix(F("ACK"), cycle); Serial.println(command);
}
void backendError(const char *cycle, const char *command, const __FlashStringHelper *code) {
  backendPrefix(F("ERR"), cycle); Serial.print(command); Serial.print(':'); Serial.println(code);
}
void backendInvalidarCalibracao() {
  const uint16_t invalid = 0;
  EEPROM.put(EEPROM_BACKEND_ADDR, invalid);
}
bool backendPontoValido(const Ponto &p, const AxisLimits &l) {
  return p.base >= l.minB && p.base <= l.maxB && p.braco >= l.minBraco && p.braco <= l.maxBraco &&
         p.cotovelo >= l.minCotovelo && p.cotovelo <= l.maxCotovelo && p.garra >= l.minG && p.garra <= l.maxG;
}
uint16_t backendHashBytes(uint16_t hash, const void *data, size_t size) {
  const byte *bytes = static_cast<const byte *>(data);
  for (size_t i = 0; i < size; ++i) hash = (hash * 31u) ^ bytes[i];
  return hash;
}
// Verifica os dados BRUTOS: carregarMemoria limita valores invalidos para o modo
// manual, mas um valor corrompido nao pode ser aceito silenciosamente no automatico.
bool backendFingerprint(uint16_t &hash) {
  uint16_t magic, limitsMagic, neutralMagic;
  EEPROM.get(0, magic); EEPROM.get(EEPROM_LIMITS_MAGIC_ADDR, limitsMagic);
  EEPROM.get(EEPROM_NEUTRAL_MAGIC_ADDR, neutralMagic);
  if (magic != EEPROM_MAGIC || limitsMagic != EEPROM_LIMITS_MAGIC || neutralMagic != EEPROM_NEUTRAL_MAGIC) return false;
  Ponto y, x, neutral; AxisLimits limits; int opened, closed;
  EEPROM.get(2, y); EEPROM.get(2 + sizeof(Ponto), x);
  EEPROM.get(2 + 2 * sizeof(Ponto), opened);
  EEPROM.get(2 + 2 * sizeof(Ponto) + sizeof(int), closed);
  EEPROM.get(EEPROM_LIMITS_DATA_ADDR, limits); EEPROM.get(EEPROM_NEUTRAL_DATA_ADDR, neutral);
  if (limits.minB < 0 || limits.maxB > 180 || limits.minB > limits.maxB ||
      limits.minBraco < 55 || limits.maxBraco > 180 || limits.minBraco > limits.maxBraco ||
      limits.minCotovelo < 55 || limits.maxCotovelo > 180 || limits.minCotovelo > limits.maxCotovelo ||
      limits.minG < 85 || limits.maxG > 180 || limits.minG > limits.maxG ||
      !backendPontoValido(y, limits) || !backendPontoValido(x, limits) || !backendPontoValido(neutral, limits) ||
      opened < limits.minG || opened > limits.maxG || closed < limits.minG || closed > limits.maxG || opened == closed) return false;
  hash = backendHashBytes(0xA531, &y, sizeof(y));
  hash = backendHashBytes(hash, &x, sizeof(x));
  hash = backendHashBytes(hash, &neutral, sizeof(neutral));
  hash = backendHashBytes(hash, &limits, sizeof(limits));
  hash = backendHashBytes(hash, &opened, sizeof(opened));
  hash = backendHashBytes(hash, &closed, sizeof(closed));
  return true;
}
bool backendCalibracaoValida() {
  uint16_t magic, stored, actual;
  EEPROM.get(EEPROM_BACKEND_ADDR, magic); EEPROM.get(EEPROM_BACKEND_ADDR + 2, stored);
  return magic == EEPROM_BACKEND_MAGIC && backendFingerprint(actual) && stored == actual;
}
bool backendPinsValidos() {
  for (int i = 0; i < 10; ++i) {
    int pin = BACKEND_ARRIVAL_PINS[i];
    if (pin == -1) continue;
    if (pin < 2 || pin >= NUM_DIGITAL_PINS || pin == PINO_BASE || pin == PINO_BRACO ||
        pin == PINO_COTOVELO || pin == PINO_GARRA || pin == PINO_SENSOR_TRIG || pin == PINO_SENSOR_ECHO) return false;
    for (int j = 0; j < i; ++j) if (pin == BACKEND_ARRIVAL_PINS[j]) return false;
  }
  return true;
}
void backendDesarmar() {
  backendDestination = -1; backendSensorStarted = false; backendSensorDone = false;
}
void backendRetire() {
  if (backendCycle[0]) {
    strcpy(backendRetired[backendRetiredIndex], backendCycle);
    backendRetiredIndex = (backendRetiredIndex + 1) % BACKEND_RETIRED;
  }
  backendCycle[0] = 0; backendCompleted = 0; backendArea = false;
  backendProfileReady = false; backendPickupCount = backendDeliveryCount = 0;
  backendPickupNext = backendDeliveryNext = 1; backendStepActive[0] = backendStepLast[0] = 0;
}
void backendParar() {
  if (cicloEmExecucao || backendAction >= 0) poseReferenciaConfirmada = false;
  abortarCiclo = true; garraMovendo = false; garraReportarFim = false;
  backendNeedsReset = true; backendDesarmar(); backendRetire();
  // Nao comanda HOME nem solta o objeto: mantem os ultimos pulsos dos servos.
}
bool backendOcupado() { return backendCycle[0] || backendAction >= 0; }
bool backendSelectCycle(const char *cycle) {
  if (strcmp(cycle, backendCycle) == 0) return true;
  for (byte i = 0; i < BACKEND_RETIRED; ++i) if (strcmp(cycle, backendRetired[i]) == 0) return false;
  if (backendCycle[0] && (backendCompleted != 15 || backendDestination >= 0)) return false;
  backendRetire(); strcpy(backendCycle, cycle); return true;
}
bool backendSensorAtivo(int index) {
  return digitalRead(BACKEND_ARRIVAL_PINS[index]) == (BACKEND_SENSOR_ACTIVE_LOW ? LOW : HIGH);
}
void backendChegada(const char *cycle) {
  backendPrefix(F("EVT"), cycle); Serial.print(F("DESTINO_ALCANCADO:R"));
  if (backendDestination < 9) Serial.print('0');
  Serial.print(backendDestination + 1); Serial.println(F(":SENSOR"));
}
void backendMonitorar() {
  if (!backendCycle[0]) return;
  unsigned long now = millis();
  if (now - backendLastValid >= BACKEND_WATCHDOG_MS ||
      (backendAction >= 0 && now - backendActionStarted >= BACKEND_ACTION_TIMEOUT_MS)) {
    backendError(backendCycle, "SISTEMA", backendAction >= 0 && now - backendActionStarted >= BACKEND_ACTION_TIMEOUT_MS ? F("MOTION_TIMEOUT") : F("COMMUNICATION_LOST"));
    backendParar(); return;
  }
  if (backendDestination < 0 || backendSensorDone) return;
  bool raw = backendSensorAtivo(backendDestination);
  if (raw != backendSensorRaw) { backendSensorRaw = raw; backendSensorChanged = now; }
  if (now - backendSensorChanged < BACKEND_DEBOUNCE_MS) return;
  if (!raw) backendSensorClear = true;
  if (raw && !backendSensorStable && backendSensorStarted && backendSensorClear) {
    backendSensorDone = true; backendChegada(backendCycle);
  }
  backendSensorStable = raw;
}
bool processarFrameBackend(const char *line) {
  if (strncmp_P(line, PSTR("CMD:"), 4) != 0) return false;
  const char *separator = strchr(line + 4, ':');
  if (!separator || separator == line + 4 || separator - (line + 4) > 32) return true;
  char cycle[33]; size_t length = separator - (line + 4);
  memcpy(cycle, line + 4, length); cycle[length] = 0;
  for (size_t i = 0; i < length; ++i)
    if (!isAlphaNumeric(cycle[i]) && cycle[i] != '_' && cycle[i] != '-') return true;
  const char *command = separator + 1;
  if (backendIs(command, F("SISTEMA:STATUS"))) {
    backendAck(cycle, command);
    backendPrefix(F("EVT"), cycle); Serial.print(F("SISTEMA_STATUS:RESET_REQUIRED="));
    Serial.print(backendNeedsReset ? '1' : '0'); Serial.print(F(":CALIBRATED="));
    Serial.print(backendCalibracaoValida() ? '1' : '0'); Serial.print(F(":POSE_REFERENCED="));
    Serial.println(poseReferenciaConfirmada ? '1' : '0');
    backendLastValid = millis(); return true;
  }
  if (strncmp_P(command, PSTR("SISTEMA:SYNC:"), 13) == 0) {
    int baseVal = 0, bracoVal = 0, cotoveloVal = 0, garraVal = 0; char trailing;
    if (cicloEmExecucao || backendAction >= 0 || sBase.attached() || sBraco.attached() ||
        sCotovelo.attached() || sGarra.attached() || backendOcupado()) {
      backendError(cycle, command, F("BUSY")); return true;
    }
    if (sscanf_P(command + 13, PSTR("%d:%d:%d:%d%c"), &baseVal, &bracoVal, &cotoveloVal, &garraVal, &trailing) != 4 ||
        baseVal != pontoNeutro.base || bracoVal != pontoNeutro.braco ||
        cotoveloVal != pontoNeutro.cotovelo || garraVal != pontoNeutro.garra ||
        baseVal < minB || baseVal > maxB || bracoVal < minBraco || bracoVal > maxBraco ||
        cotoveloVal < minCotovelo || cotoveloVal > maxCotovelo || garraVal < minG || garraVal > maxG) {
      backendError(cycle, command, F("NEUTRAL_MISMATCH")); return true;
    }
    angB = baseVal; angBraco = bracoVal; angCotovelo = cotoveloVal; angG = destinoGarra = garraVal;
    poseReferenciaConfirmada = true; backendLastValid = millis(); backendAck(cycle, command);
    backendPrefix(F("EVT"), cycle); Serial.println(F("POSE_REFERENCE_CONFIRMED")); return true;
  }
  if (strncmp_P(command, PSTR("PRESENCA:CONFIGURAR:"), 20) == 0) {
    int distance = 0; unsigned long stable = 0; char trailing;
    if (sscanf_P(command + 20, PSTR("%d:%lu%c"), &distance, &stable, &trailing) != 2 ||
        distance < 2 || distance > 100 || (stable != 3000 && stable != 4000 && stable != 5000)) {
      backendError(cycle, command, F("INVALID_SENSOR_CONFIG")); return true;
    }
    if (cicloEmExecucao) { backendError(cycle, command, F("BUSY")); return true; }
    sensorDistanceCm = distance; sensorStableMs = stable; sensorEnabled = true;
    reiniciarDeteccaoSensor();
    backendLastValid = millis(); backendAck(cycle, command); return true;
  }
  // Medicao avulsa (9 disparos, ~0,4 s) para conferir o fundo da bancada.
  if (backendIs(command, F("PRESENCA:LEITURA"))) {
    if (cicloEmExecucao) { backendError(cycle, command, F("BUSY")); return true; }
    int amostras[9]; int menor = SENSOR_SEM_ECO, maior = -1; byte validas = 0;
    for (byte i = 0; i < 9; ++i) {
      amostras[i] = medirDistanciaCm();
      if (amostras[i] != SENSOR_SEM_ECO) { ++validas; menor = min(menor, amostras[i]); maior = max(maior, amostras[i]); }
      delay(40);
    }
    int mediana = medianaCm(amostras, 9);
    backendLastValid = millis(); backendAck(cycle, command);
    backendPrefix(F("EVT"), cycle); Serial.print(F("PRESENCA_LEITURA:"));
    Serial.print(mediana == SENSOR_SEM_ECO ? -1 : mediana); Serial.print(':');
    Serial.print(validas ? menor : -1); Serial.print(':'); Serial.print(maior); Serial.print(':');
    Serial.println(validas);
    return true;
  }
  // Solta os servos para o operador alinhar o braco antes de SISTEMA:SYNC.
  if (backendIs(command, F("SISTEMA:LIBERAR"))) {
    if (cicloEmExecucao || backendAction >= 0) { backendError(cycle, command, F("BUSY")); return true; }
    desenergizarServos(); poseReferenciaConfirmada = false;
    backendLastValid = millis(); backendAck(cycle, command); return true;
  }
  if (backendIs(command, F("SISTEMA:PING"))) {
    backendLastValid = millis(); backendAck(cycle, command); return true;
  }
  bool reset = backendIs(command, F("SISTEMA:RESET"));
  if (reset || backendIs(command, F("GARRA:STOP")) || backendIs(command, F("ESTEIRA:STOP"))) {
    bool moving = cicloEmExecucao;
    backendParar(); backendLastValid = millis();
    // Reset durante movimento interrompe; outro Reset sera necessario ao terminar.
    if (reset && !moving) { backendNeedsReset = false; abortarCiclo = false; }
    backendAck(cycle, command); return true;
  }
  if (backendIs(command, F("SENSOR:DESARMAR"))) {
    if (backendCycle[0] && strcmp(cycle, backendCycle)) { backendError(cycle, command, F("WRONG_CYCLE")); return true; }
    backendLastValid = millis(); backendDesarmar();
    if (backendCompleted == 15) backendRetire();
    backendAck(cycle, command); return true;
  }
  int action = -1;
  for (byte i = 0; i < 4; ++i) if (backendIs(command, backendCommand(i))) action = i;
  bool profile = strncmp_P(command, PSTR("GARRA:PERFIL:"), 13) == 0;
  bool profileStep = strncmp_P(command, PSTR("GARRA:PASSO:"), 12) == 0;
  bool area = backendIs(command, F("GARRA:AREA:P01"));
  bool arm = strncmp_P(command, PSTR("SENSOR:ARMAR:"), 13) == 0;
  bool start = strncmp_P(command, PSTR("SENSOR:INICIAR:"), 15) == 0;
  if (action < 0 && !area && !arm && !start && !profile && !profileStep) { backendError(cycle, command, F("COMMAND_NOT_SUPPORTED")); return true; }
  if (backendNeedsReset) { backendError(cycle, command, F("RESET_REQUIRED")); return true; }
  if (cicloEmExecucao && backendAction < 0) { backendError(cycle, command, F("MANUAL_MOVEMENT_ACTIVE")); return true; }
  if (!backendCalibracaoValida()) { backendError(cycle, command, F("CALIBRATION_NOT_VALIDATED")); return true; }
  if (!backendPinsValidos()) { backendError(cycle, command, F("INVALID_PINS")); return true; }
  if ((profile || profileStep || area || action >= 0) && !poseReferenciaConfirmada) {
    backendError(cycle, command, F("POSE_SYNC_REQUIRED")); return true;
  }
  if (!backendSelectCycle(cycle)) { backendError(cycle, command, F("CYCLE_LOCKED")); return true; }
  if (profile) {
    int pickupCount = 0, deliveryCount = 0, speed = 0; char trailing;
    if (sscanf_P(command + 13, PSTR("%d:%d:%d%c"), &pickupCount, &deliveryCount, &speed, &trailing) != 3 ||
        pickupCount < 1 || pickupCount > 20 || deliveryCount < 1 || deliveryCount > 20 ||
        (speed != 16 && speed != 24 && speed != 32)) {
      backendError(cycle, command, F("INVALID_PROFILE")); return true;
    }
    if (backendAction >= 0 || backendArea) { backendError(cycle, command, F("BUSY")); return true; }
    backendPickupCount = pickupCount; backendDeliveryCount = deliveryCount; backendSpeedMs = speed;
    backendPickupNext = backendDeliveryNext = 1; backendStepActive[0] = backendStepLast[0] = 0;
    backendProfileReady = true; velocidadeMs = speed; backendLastValid = millis(); backendAck(cycle, command); return true;
  }
  if (arm || start) {
    const char *destination = command + (arm ? 13 : 15);
    if (strlen(destination) != 3 || destination[0] != 'R' || !isDigit(destination[1]) || !isDigit(destination[2])) {
      backendError(cycle, command, F("INVALID_DESTINATION")); return true;
    }
    int index = (destination[1] - '0') * 10 + destination[2] - '0' - 1;
    if (index < 0 || index > 9 || BACKEND_ARRIVAL_PINS[index] < 0) { backendError(cycle, command, F("SENSOR_NOT_CONFIGURED")); return true; }
    if (backendDestination >= 0 && backendDestination != index) { backendError(cycle, command, F("DESTINATION_LOCKED")); return true; }
    if (arm && backendDestination < 0) {
      if (backendSensorAtivo(index)) { backendError(cycle, command, F("SENSOR_BLOCKED")); return true; }
      backendDestination = index; backendSensorStarted = backendSensorDone = false;
      backendSensorRaw = backendSensorStable = backendSensorClear = false; backendSensorChanged = millis();
    } else if (start && !backendSensorStarted) {
      if (backendDestination != index || backendCompleted != 15) { backendError(cycle, command, F("INVALID_STAGE")); return true; }
      if (backendSensorAtivo(index) || backendSensorRaw || backendSensorStable || !backendSensorClear ||
          millis() - backendSensorChanged < BACKEND_DEBOUNCE_MS) { backendError(cycle, command, F("SENSOR_BLOCKED")); return true; }
      backendSensorStarted = true;
    }
    backendLastValid = millis(); backendAck(cycle, command);
    if (start && backendSensorDone) backendChegada(cycle);
    return true;
  }
  if (area) {
    if (!backendProfileReady) { backendError(cycle, command, F("PROFILE_REQUIRED")); return true; }
    backendArea = true; backendLastValid = millis(); backendAck(cycle, command); return true;
  }
  if (profileStep) {
    char phase = 0, trailing = 0; int order = 0, baseVal = 0, bracoVal = 0, cotoveloVal = 0, garraVal = 0, pause = 0;
    if (strlen(command) >= sizeof(backendStepActive) ||
        sscanf_P(command, PSTR("GARRA:PASSO:%c:%d:%d:%d:%d:%d:%d%c"), &phase, &order, &baseVal,
               &bracoVal, &cotoveloVal, &garraVal, &pause, &trailing) != 7 ||
        (phase != 'P' && phase != 'E') || order < 1 || pause < 0 || pause > 10000) {
      backendError(cycle, command, F("INVALID_STEP")); return true;
    }
    Ponto target = {baseVal, bracoVal, cotoveloVal, garraVal};
    if (!backendProfileReady || !backendArea || !backendPontoValido(target, {minB, maxB, minBraco, maxBraco, minCotovelo, maxCotovelo, minG, maxG})) {
      backendError(cycle, command, F("INVALID_PROFILE_OR_POSE")); return true;
    }
    if (backendAction == 4) {
      if (strcmp(backendStepActive, command) == 0) { backendLastValid = millis(); backendAck(cycle, command); return true; }
      backendError(cycle, command, F("BUSY")); return true;
    }
    if (strcmp(backendStepLast, command) == 0) {
      backendLastValid = millis(); backendAck(cycle, command); backendPrefix(F("EVT"), cycle);
      Serial.print(F("GARRA_PASSO_CONCLUIDO:")); Serial.print(phase); Serial.print(':'); Serial.println(order); return true;
    }
    bool expected = phase == 'P' ? backendPickupNext == order && order <= backendPickupCount
                                 : backendDeliveryNext == order && order <= backendDeliveryCount && backendPickupNext > backendPickupCount;
    if (!expected || backendAction >= 0 || backendCompleted != 0) { backendError(cycle, command, F("INVALID_STAGE")); return true; }
    backendAction = 4; backendActionStarted = backendLastValid = millis(); strcpy(backendStepActive, command);
    cicloEmExecucao = true; abortarCiclo = false; backendAck(cycle, command);
    moverSuave(baseVal, bracoVal, cotoveloVal, garraVal, backendSpeedMs);
    if (!abortarCiclo && pause > 0) aguardarCiclo(pause);
    cicloEmExecucao = false; backendAction = -1; backendStepActive[0] = 0;
    if (!abortarCiclo) {
      strcpy(backendStepLast, command);
      if (phase == 'P') {
        ++backendPickupNext;
        if (backendPickupNext > backendPickupCount) backendDeliveryNext = 1;
      } else {
        ++backendDeliveryNext;
        if (backendDeliveryNext > backendDeliveryCount) backendCompleted = 15;
      }
      backendPrefix(F("EVT"), cycle); Serial.print(F("GARRA_PASSO_CONCLUIDO:"));
      Serial.print(phase); Serial.print(':'); Serial.println(order);
    } else {
      backendParar(); backendError(cycle, command, F("CYCLE_STOPPED"));
    }
    return true;
  }
  if (backendCompleted & (1 << action)) {
    backendLastValid = millis(); backendAck(cycle, command);
    backendPrefix(F("EVT"), cycle); Serial.println(backendEvent(action)); return true;
  }
  if (backendAction == action) { backendLastValid = millis(); backendAck(cycle, command); return true; }
  if (backendAction >= 0 || !backendArea || backendCompleted != (1 << action) - 1) { backendError(cycle, command, F("INVALID_STAGE")); return true; }
  backendAction = action; backendActionStarted = backendLastValid = millis();
  cicloEmExecucao = true; abortarCiclo = false;
  backendAck(cycle, command);  // Sempre antes de movimentar.
  bool finished = executarEtapaXY(action);
  cicloEmExecucao = false; backendAction = -1;
  if (finished && !abortarCiclo) {
    backendCompleted |= 1 << action;
    backendPrefix(F("EVT"), cycle); Serial.println(backendEvent(action));
  } else {
    backendParar(); backendError(cycle, command, F("CYCLE_STOPPED"));
  }
  return true;
}
bool processarComandoAuto(const char *command) {
  if (strncmp_P(command, PSTR("AUTO:"), 5)) return false;
  if (backendOcupado() || cicloEmExecucao) { Serial.println(F("[AUTO] Ocupado; pare antes de alterar a validacao.")); return true; }
  if (backendIs(command, F("AUTO:INVALIDAR"))) backendInvalidarCalibracao();
  else if (backendIs(command, F("AUTO:VALIDAR"))) {
    uint16_t hash;
    if (!backendFingerprint(hash)) {
      Serial.println(F("[AUTO] Salve e confira Y, X, N, limites e GCALIB antes de validar."));
      Serial.println(F("[AUTO_STATUS] EEPROM=INVALIDA"));
      return true;
    }
    // Publica o marcador por ultimo; gravacao parcial nao libera o automatico.
    backendInvalidarCalibracao(); EEPROM.put(EEPROM_BACKEND_ADDR + 2, hash);
    EEPROM.put(EEPROM_BACKEND_ADDR, EEPROM_BACKEND_MAGIC);
  } else if (!backendIs(command, F("AUTO:STATUS"))) { Serial.println(F("[AUTO] Use AUTO:VALIDAR, AUTO:INVALIDAR ou AUTO:STATUS.")); return true; }
  Serial.print(F("[AUTO] Calibracao EEPROM validada: ")); Serial.println(backendCalibracaoValida() ? F("SIM") : F("NAO"));
  Serial.print(F("[AUTO_STATUS] EEPROM=")); Serial.println(backendCalibracaoValida() ? F("VALIDA") : F("INVALIDA"));
  return true;
}
void backendSetup() {
  if (backendPinsValidos()) for (byte i = 0; i < 10; ++i)
    if (BACKEND_ARRIVAL_PINS[i] >= 0) pinMode(BACKEND_ARRIVAL_PINS[i], INPUT_PULLUP);
  Serial.println(F("[AUTO] Ponte backend pronta; RESET nao executa homing."));
}
