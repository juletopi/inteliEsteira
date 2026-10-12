#include <Servo.h>
#include <EEPROM.h>

// =========================================================================
// 1. PINOS DOS MOTORES
// =========================================================================
const int PINO_BASE     = 10; // Base giratória horizontal (Pino 10)
const int PINO_BRACO    = 11; // Motor principal do Braço / Ombro (Pino 11)
const int PINO_COTOVELO = 6;  // Motor complementar do Cotovelo / Alavanca (Pino 6)
const int PINO_GARRA    = 3;  // Garra de abertura e aperto (Pino 3)
// HC-SR04. Mude estes dois pinos se sua montagem usar outra fiação.
const int PINO_SENSOR_TRIG = 8;
const int PINO_SENSOR_ECHO = 9;

// LIMITES FÍSICOS DE SEGURANÇA (Evitam que o acrílico bata nos batentes e trave)
int minB        = 0,   maxB        = 180; // Servo.write aceita comandos de 0° a 180°
int minBraco    = 55,  maxBraco    = 180; // Testar devagar; parar antes do batente
int minCotovelo = 55,  maxCotovelo = 180; // Testar devagar; parar antes do batente
int minG        = 85,  maxG        = 180; // Informado: 85° fecha; abertura será testada

// POSIÇÕES INICIAIS SEGURAS (HOME NEUTRA)
const int HOME_B        = 90;
const int HOME_BRACO    = 80;
const int HOME_COTOVELO = 80;
const int HOME_G        = 120; // Inicial de teste; confirmar abertura sem forçar

// =========================================================================
// 2. OBJETOS E ESTADO
// =========================================================================
Servo sBase, sBraco, sCotovelo, sGarra;

int angB        = HOME_B;
int angBraco    = HOME_BRACO;
int angCotovelo = HOME_COTOVELO;
int angG        = HOME_G;
int destinoGarra = HOME_G;
bool garraMovendo = false;
bool garraReportarFim = false;
unsigned long ultimoPassoGarra = 0;
const unsigned long INTERVALO_GARRA_MS = 40;

bool servosAtivos = false;
bool garraAtiva   = false;
int velocidadeMs  = 24;

// Valores iniciais da garra (aberta 120°, fechada 85°)
int angGarraAberta  = 158;
int angGarraFechada = 86;

struct Ponto {
  int base;
  int braco;
  int cotovelo;
  int garra;
};

// Posições padrão para primeiro uso dentro da faixa segura
Ponto pontoY = {150, 80, 80, 85}; // Posição padrão de estoque
Ponto pontoX = {20,  80, 80, 120}; // Posição padrão de esteira
Ponto pontoNeutro = {HOME_B, HOME_BRACO, HOME_COTOVELO, HOME_G};

const uint16_t EEPROM_MAGIC = 0xB00B;
const uint16_t EEPROM_NEUTRAL_MAGIC = 0x4E45;
const int EEPROM_NEUTRAL_MAGIC_ADDR = 44;
const int EEPROM_NEUTRAL_DATA_ADDR = 46;
const uint16_t EEPROM_LIMITS_MAGIC = 0xCA11;
const int EEPROM_LIMITS_MAGIC_ADDR = 24;
const int EEPROM_LIMITS_DATA_ADDR = 26;

struct AxisLimits {
  int minB, maxB;
  int minBraco, maxBraco;
  int minCotovelo, maxCotovelo;
  int minG, maxG;
};

// Buffer de leitura serial não-bloqueante
char serialBuf[32];
byte bufIdx = 0;
bool cicloEmExecucao = false;
bool abortarCiclo = false;

const uint16_t EEPROM_SENSOR_MAGIC = 0x534E;
const int EEPROM_SENSOR_MAGIC_ADDR = 70;
const int EEPROM_SENSOR_DATA_ADDR = 72;
bool sensorEnabled = false;
int sensorDistanceCm = 10;
unsigned long sensorStableMs = 3000;
unsigned long sensorLastReadAt = 0;
unsigned long sensorCandidateSince = 0;
unsigned long sensorClearSince = 0;
bool sensorCandidate = false;
bool sensorPresent = false;

void salvarConfigSensor() {
  EEPROM.put(EEPROM_SENSOR_MAGIC_ADDR, EEPROM_SENSOR_MAGIC);
  EEPROM.put(EEPROM_SENSOR_DATA_ADDR, sensorEnabled);
  EEPROM.put(EEPROM_SENSOR_DATA_ADDR + sizeof(bool), sensorDistanceCm);
  EEPROM.put(EEPROM_SENSOR_DATA_ADDR + sizeof(bool) + sizeof(int), sensorStableMs);
}

void carregarConfigSensor() {
  uint16_t magic = 0;
  EEPROM.get(EEPROM_SENSOR_MAGIC_ADDR, magic);
  if (magic != EEPROM_SENSOR_MAGIC) return;
  EEPROM.get(EEPROM_SENSOR_DATA_ADDR, sensorEnabled);
  EEPROM.get(EEPROM_SENSOR_DATA_ADDR + sizeof(bool), sensorDistanceCm);
  EEPROM.get(EEPROM_SENSOR_DATA_ADDR + sizeof(bool) + sizeof(int), sensorStableMs);
  if (sensorDistanceCm < 2 || sensorDistanceCm > 100) sensorDistanceCm = 10;
  if (sensorStableMs < 3000 || sensorStableMs > 5000) sensorStableMs = 3000;
}

void monitorarSensor() {
  if (!sensorEnabled || cicloEmExecucao || millis() - sensorLastReadAt < 60) return;
  sensorLastReadAt = millis();
  digitalWrite(PINO_SENSOR_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PINO_SENSOR_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PINO_SENSOR_TRIG, LOW);
  unsigned long duracao = pulseIn(PINO_SENSOR_ECHO, HIGH, 25000UL);
  int distancia = duracao ? (int)(duracao / 58UL) : -1;
  unsigned long agora = millis();
  bool dentro = distancia >= 2 && distancia <= sensorDistanceCm;

  if (dentro) {
    sensorClearSince = 0;
    if (!sensorCandidate) {
      sensorCandidate = true;
      sensorCandidateSince = agora;
    }
    if (!sensorPresent && agora - sensorCandidateSince >= sensorStableMs) {
      sensorPresent = true;
      Serial.print(F("SENSOR:PRESENTE:")); Serial.println(distancia);
    }
  } else {
    sensorCandidate = false;
    if (sensorPresent) {
      if (!sensorClearSince) sensorClearSince = agora;
      else if (agora - sensorClearSince >= 300) {
        sensorPresent = false;
        sensorClearSince = 0;
        Serial.print(F("SENSOR:AUSENTE:")); Serial.println(distancia);
      }
    }
  }
}

bool verificarParadaCiclo() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      serialBuf[bufIdx] = '\0';
      if (strcmp(serialBuf, "STOP") == 0 || strcmp(serialBuf, "FREE") == 0) {
        abortarCiclo = true;
        if (sBase.attached()) sBase.detach();
        if (sBraco.attached()) sBraco.detach();
        if (sCotovelo.attached()) sCotovelo.detach();
        if (sGarra.attached()) sGarra.detach();
        servosAtivos = false;
        garraAtiva = false;
        Serial.println(F("[CICLO] Interrompido; servos soltos."));
        bufIdx = 0;
        return true;
      }
      bufIdx = 0; // Outros comandos são ignorados enquanto o ciclo roda.
    } else if (bufIdx < sizeof(serialBuf) - 1) {
      serialBuf[bufIdx++] = c;
    } else {
      bufIdx = 0;
    }
  }
  return abortarCiclo;
}

void aguardarCiclo(int ms) {
  for (int decorrido = 0; decorrido < ms; decorrido += 5) {
    if (verificarParadaCiclo()) return;
    delay(5);
  }
}

// =========================================================================
// 3. CONTROLE DE ENERGIA DOS SERVOS
// =========================================================================
void energizarServos() {
  if (!sBase.attached())     { sBase.attach(PINO_BASE);         sBase.write(angB); delay(60); }
  if (!sBraco.attached())    { sBraco.attach(PINO_BRACO);       sBraco.write(angBraco); delay(60); }
  if (!sCotovelo.attached()) { sCotovelo.attach(PINO_COTOVELO); sCotovelo.write(angCotovelo); delay(60); }
  if (!sGarra.attached())    { sGarra.attach(PINO_GARRA);       sGarra.write(angG); delay(60); }

  servosAtivos = true;
  garraAtiva   = true;
  Serial.println(F("[SERVOS] Motores ENERGIZADOS."));
}

void desenergizarServos() {
  garraMovendo = false;
  garraReportarFim = false;
  if (sBase.attached())     sBase.detach();
  if (sBraco.attached())    sBraco.detach();
  if (sCotovelo.attached()) sCotovelo.detach();
  if (sGarra.attached())    sGarra.detach();

  servosAtivos = false;
  garraAtiva   = false;
  Serial.println(F("[SERVOS] Motores LIVRES! (FREE)"));
}

void desenergizarGarra() {
  garraMovendo = false;
  garraReportarFim = false;
  if (sGarra.attached()) sGarra.detach();
  garraAtiva = false;
  Serial.println(F("[GARRA] Garra desenergizada."));
}

void energizarGarra() {
  if (!sGarra.attached()) sGarra.attach(PINO_GARRA);
  sGarra.write(angG);
  garraAtiva = true;
  Serial.print(F("[GARRA] Garra ativa em ")); Serial.print(angG); Serial.println(F("°"));
}

// =========================================================================
// 4. MEMÓRIA EEPROM
// =========================================================================
void imprimirCoords(const Ponto &p) {
  Serial.print(p.base); Serial.print(F(","));
  Serial.print(p.braco); Serial.print(F(","));
  Serial.print(p.cotovelo); Serial.print(F(","));
  Serial.println(p.garra);
}

void imprimirPontos() {
  Serial.print(F("Ponto Y: B:")); Serial.print(pontoY.base);
  Serial.print(F(" Braco:")); Serial.print(pontoY.braco);
  Serial.print(F(" Cotovelo:")); Serial.print(pontoY.cotovelo);
  Serial.print(F(" G:")); Serial.println(pontoY.garra);

  Serial.print(F("Ponto X: B:")); Serial.print(pontoX.base);
  Serial.print(F(" Braco:")); Serial.print(pontoX.braco);
  Serial.print(F(" Cotovelo:")); Serial.print(pontoX.cotovelo);
  Serial.print(F(" G:")); Serial.println(pontoX.garra);

  Serial.print(F("Ponto Neutro: B:")); Serial.print(pontoNeutro.base);
  Serial.print(F(" Braco:")); Serial.print(pontoNeutro.braco);
  Serial.print(F(" Cotovelo:")); Serial.print(pontoNeutro.cotovelo);
  Serial.print(F(" G:")); Serial.println(pontoNeutro.garra);

  Serial.print(F("Garra: Aberta=")); Serial.print(angGarraAberta);
  Serial.print(F("° | Fechada=")); Serial.print(angGarraFechada); Serial.println(F("°"));
  Serial.print(F("[LIMITES] B=")); Serial.print(minB); Serial.print(F(":")); Serial.print(maxB);
  Serial.print(F(" A=")); Serial.print(minBraco); Serial.print(F(":")); Serial.print(maxBraco);
  Serial.print(F(" C=")); Serial.print(minCotovelo); Serial.print(F(":")); Serial.print(maxCotovelo);
  Serial.print(F(" G=")); Serial.print(minG); Serial.print(F(":")); Serial.println(maxG);
}

void carregarMemoria() {
  uint16_t magic = 0;
  EEPROM.get(0, magic);

  if (magic == EEPROM_MAGIC) {
    EEPROM.get(2, pontoY);
    EEPROM.get(2 + sizeof(Ponto), pontoX);
    EEPROM.get(2 + 2 * sizeof(Ponto), angGarraAberta);
    EEPROM.get(2 + 2 * sizeof(Ponto) + sizeof(int), angGarraFechada);
    uint16_t limitsMagic = 0;
    EEPROM.get(EEPROM_LIMITS_MAGIC_ADDR, limitsMagic);
    if (limitsMagic == EEPROM_LIMITS_MAGIC) {
      AxisLimits saved;
      EEPROM.get(EEPROM_LIMITS_DATA_ADDR, saved);
      if (saved.minB >= 0 && saved.minB <= saved.maxB && saved.maxB <= 180) { minB = saved.minB; maxB = saved.maxB; }
      if (saved.minBraco >= 55 && saved.minBraco <= saved.maxBraco && saved.maxBraco <= 180) { minBraco = saved.minBraco; maxBraco = saved.maxBraco; }
      if (saved.minCotovelo >= 55 && saved.minCotovelo <= saved.maxCotovelo && saved.maxCotovelo <= 180) { minCotovelo = saved.minCotovelo; maxCotovelo = saved.maxCotovelo; }
      if (saved.minG >= 85 && saved.minG <= saved.maxG && saved.maxG <= 180) { minG = saved.minG; maxG = saved.maxG; }
    }
    pontoY.base = constrain(pontoY.base, minB, maxB);
    pontoY.braco = constrain(pontoY.braco, minBraco, maxBraco);
    pontoY.cotovelo = constrain(pontoY.cotovelo, minCotovelo, maxCotovelo);
    pontoY.garra = constrain(pontoY.garra, minG, maxG);
    pontoX.base = constrain(pontoX.base, minB, maxB);
    pontoX.braco = constrain(pontoX.braco, minBraco, maxBraco);
    pontoX.cotovelo = constrain(pontoX.cotovelo, minCotovelo, maxCotovelo);
    pontoX.garra = constrain(pontoX.garra, minG, maxG);
    uint16_t neutralMagic = 0;
    EEPROM.get(EEPROM_NEUTRAL_MAGIC_ADDR, neutralMagic);
    if (neutralMagic == EEPROM_NEUTRAL_MAGIC) EEPROM.get(EEPROM_NEUTRAL_DATA_ADDR, pontoNeutro);
    pontoNeutro.base = constrain(pontoNeutro.base, minB, maxB);
    pontoNeutro.braco = constrain(pontoNeutro.braco, minBraco, maxBraco);
    pontoNeutro.cotovelo = constrain(pontoNeutro.cotovelo, minCotovelo, maxCotovelo);
    pontoNeutro.garra = constrain(pontoNeutro.garra, minG, maxG);
    angGarraAberta = constrain(angGarraAberta, minG, maxG);
    angGarraFechada = constrain(angGarraFechada, minG, maxG);
    Serial.println(F("[EEPROM] Calibracoes anteriores carregadas com sucesso!"));
  } else {
    Serial.println(F("[EEPROM] Memoria inicializada com valores seguros de fabrica."));
  }

  imprimirPontos();
}

void inicializarEEPROMSePreciso() {
  uint16_t magic = 0;
  EEPROM.get(0, magic);
  if (magic != EEPROM_MAGIC) {
    EEPROM.put(0, EEPROM_MAGIC);
    EEPROM.put(2, pontoY);
    EEPROM.put(2 + sizeof(Ponto), pontoX);
    EEPROM.put(2 + 2 * sizeof(Ponto), angGarraAberta);
    EEPROM.put(2 + 2 * sizeof(Ponto) + sizeof(int), angGarraFechada);
  }
}

void salvarLimites() {
  inicializarEEPROMSePreciso();
  AxisLimits current = {minB, maxB, minBraco, maxBraco, minCotovelo, maxCotovelo, minG, maxG};
  EEPROM.put(EEPROM_LIMITS_MAGIC_ADDR, EEPROM_LIMITS_MAGIC);
  EEPROM.put(EEPROM_LIMITS_DATA_ADDR, current);
}

bool atualizarLimite(char eixo, int novoMin, int novoMax) {
  int *atualMin = nullptr;
  int *atualMax = nullptr;
  int hardMin = 0;
  int hardMax = 180;
  if (eixo == 'B') { atualMin = &minB; atualMax = &maxB; }
  else if (eixo == 'A') { atualMin = &minBraco; atualMax = &maxBraco; hardMin = 55; }
  else if (eixo == 'C') { atualMin = &minCotovelo; atualMax = &maxCotovelo; hardMin = 55; }
  else if (eixo == 'G') { atualMin = &minG; atualMax = &maxG; hardMin = 85; }
  if (!atualMin || novoMin < hardMin || novoMax > hardMax || novoMin > novoMax) return false;
  *atualMin = novoMin;
  *atualMax = novoMax;
  salvarLimites();
  Serial.print(F("[LIMITE SALVO] ")); Serial.print(eixo); Serial.print(F("="));
  Serial.print(novoMin); Serial.print(F(":")); Serial.println(novoMax);
  return true;
}

void salvarPontoY() {
  pontoY = {angB, angBraco, angCotovelo, angG};
  inicializarEEPROMSePreciso();
  EEPROM.put(2, pontoY);
  Serial.print(F("[EEPROM] Ponto Y Salvo: "));
  imprimirCoords(pontoY);
}

void salvarPontoX() {
  pontoX = {angB, angBraco, angCotovelo, angG};
  inicializarEEPROMSePreciso();
  EEPROM.put(2 + sizeof(Ponto), pontoX);
  Serial.print(F("[EEPROM] Ponto X Salvo: "));
  imprimirCoords(pontoX);
}

void salvarPontoNeutro() {
  pontoNeutro = {angB, angBraco, angCotovelo, angG};
  inicializarEEPROMSePreciso();
  EEPROM.put(EEPROM_NEUTRAL_MAGIC_ADDR, EEPROM_NEUTRAL_MAGIC);
  EEPROM.put(EEPROM_NEUTRAL_DATA_ADDR, pontoNeutro);
  Serial.println(F("[EEPROM] Ponto Neutro salvo."));
  Serial.print(F("Ponto Neutro: B:")); Serial.print(pontoNeutro.base);
  Serial.print(F(" Braco:")); Serial.print(pontoNeutro.braco);
  Serial.print(F(" Cotovelo:")); Serial.print(pontoNeutro.cotovelo);
  Serial.print(F(" G:")); Serial.println(pontoNeutro.garra);
}

void salvarGarraCalib(int aberta, int fechada) {
  angGarraAberta  = constrain(aberta, minG, maxG);
  angGarraFechada = constrain(fechada, minG, maxG);
  inicializarEEPROMSePreciso();
  EEPROM.put(2 + 2 * sizeof(Ponto), angGarraAberta);
  EEPROM.put(2 + 2 * sizeof(Ponto) + sizeof(int), angGarraFechada);
  Serial.print(F("[GARRA] Calibracao Salva: Aberta=")); Serial.print(angGarraAberta);
  Serial.print(F("° | Fechada=")); Serial.print(angGarraFechada); Serial.println(F("°"));
  Serial.print(F("[LIMITES] B=")); Serial.print(minB); Serial.print(F(":")); Serial.print(maxB);
  Serial.print(F(" A=")); Serial.print(minBraco); Serial.print(F(":")); Serial.print(maxBraco);
  Serial.print(F(" C=")); Serial.print(minCotovelo); Serial.print(F(":")); Serial.print(maxCotovelo);
  Serial.print(F(" G=")); Serial.print(minG); Serial.print(F(":")); Serial.println(maxG);
}

// =========================================================================
// 5. MOVIMENTAÇÃO SUAVE E COORDENADA (Braço 11 + Cotovelo 9)
// =========================================================================
void moverSuave(int destB, int destBraco, int destCotovelo, int destG, int delayMs = 16) {
  // A posição gravada passa a ser a origem confiável de qualquer movimento seguinte.
  garraMovendo = false;
  garraReportarFim = false;
  if (!servosAtivos) energizarServos();
  if (!garraAtiva)   energizarGarra();

  destB        = constrain(destB, minB, maxB);
  destBraco    = constrain(destBraco, minBraco, maxBraco);
  destCotovelo = constrain(destCotovelo, minCotovelo, maxCotovelo);
  destG        = constrain(destG, minG, maxG);

  bool mov = true;
  while (mov) {
    if (cicloEmExecucao && verificarParadaCiclo()) return;
    mov = false;

    if (angB < destB) { angB++; mov = true; } else if (angB > destB) { angB--; mov = true; }
    if (angBraco < destBraco) { angBraco++; mov = true; } else if (angBraco > destBraco) { angBraco--; mov = true; }
    if (angCotovelo < destCotovelo) { angCotovelo++; mov = true; } else if (angCotovelo > destCotovelo) { angCotovelo--; mov = true; }
    if (angG < destG) { angG++; mov = true; } else if (angG > destG) { angG--; mov = true; }

    sBase.write(angB);
    sBraco.write(angBraco);
    sCotovelo.write(angCotovelo);
    sGarra.write(angG);

    if (cicloEmExecucao) aguardarCiclo(delayMs);
    else delay(delayMs);
  }
  destinoGarra = angG;
}

// Comandos manuais da garra mudam o alvo; o loop aproxima o servo gradualmente.
void definirDestinoGarra(int destino, bool reportarFim = false) {
  energizarGarra();
  destinoGarra = constrain(destino, minG, maxG);
  garraReportarFim = reportarFim;
  garraMovendo = (angG != destinoGarra);
  ultimoPassoGarra = millis();
  if (!garraMovendo && garraReportarFim) {
    Serial.print(F("[GARRA_DONE]:")); Serial.println(angG);
    garraReportarFim = false;
  }
}

void atualizarGarraSuave() {
  if (!garraMovendo || !sGarra.attached()) return;
  if (millis() - ultimoPassoGarra < INTERVALO_GARRA_MS) return;
  ultimoPassoGarra = millis();

  if (angG < destinoGarra) angG++;
  else if (angG > destinoGarra) angG--;
  sGarra.write(angG);

  if (angG == destinoGarra) {
    garraMovendo = false;
    if (garraReportarFim) {
      Serial.print(F("[GARRA_DONE]:")); Serial.println(angG);
      garraReportarFim = false;
    }
  }
}

// Move ombro e cotovelo em passos sincronizados para evitar saltos de posição.
void moverBracoJunto(int novoBraco, int novoCotovelo) {
  novoBraco    = constrain(novoBraco, minBraco, maxBraco);
  novoCotovelo = constrain(novoCotovelo, minCotovelo, maxCotovelo);

  if (!sBraco.attached()) {
    sBraco.attach(PINO_BRACO);
    sBraco.write(angBraco);
    delay(40);
  }
  if (!sCotovelo.attached()) {
    sCotovelo.attach(PINO_COTOVELO);
    sCotovelo.write(angCotovelo);
    delay(40);
  }

  int inicioBraco = angBraco;
  int inicioCotovelo = angCotovelo;
  int deltaBraco = novoBraco - inicioBraco;
  int deltaCotovelo = novoCotovelo - inicioCotovelo;
  int passos = max(abs(deltaBraco), abs(deltaCotovelo));
  if (passos == 0) return;

  for (int passo = 1; passo <= passos; passo++) {
    angBraco = inicioBraco + (long)deltaBraco * passo / passos;
    angCotovelo = inicioCotovelo + (long)deltaCotovelo * passo / passos;
    sBraco.write(angBraco);
    sCotovelo.write(angCotovelo);
    delay(velocidadeMs);
  }
}

// Diagnóstico específico do motor no Pino 11
void diagnosticarPino11() {
  Serial.println(F("========================================"));
  Serial.println(F("[DIAGNOSTICO PINO 11] Teste de pulso e engrenagem..."));

  if (!sBraco.attached()) sBraco.attach(PINO_BRACO);

  // Teste 1: Pulso Neutro (1500us = 90 graus)
  Serial.println(F("[PASSO 1] Enviando pulso neutro (1500us / ~90°)..."));
  sBraco.writeMicroseconds(1500);
  delay(600);

  // Teste 2: Pequeno avanço suave (1650us = ~105°)
  Serial.println(F("[PASSO 2] Tentando avanco suave (+15° / 1650us)..."));
  sBraco.writeMicroseconds(1650);
  delay(600);

  // Teste 3: Pequeno recuo suave (1350us = ~75°)
  Serial.println(F("[PASSO 3] Tentando recuo suave (-15° / 1350us)..."));
  sBraco.writeMicroseconds(1350);
  delay(600);

  // Teste 4: Voltar ao neutro
  Serial.println(F("[PASSO 4] Retornando ao centro (1500us)..."));
  sBraco.writeMicroseconds(1500);
  delay(400);

  // Desliga imediatamente para não queimar se estiver preso
  sBraco.detach();
  Serial.println(F("[FIM] Motor 11 DESLIGADO automaticamente por seguranca."));
  Serial.println(F("--> OBSERVE: O braco se moveu fisicamente ou o motor interno apenas girou rangendo?"));
  Serial.println(F("========================================"));
}

// Teste suave da Garra
void testarGarraLento() {
  energizarGarra();
  Serial.println(F("[GARRA] Testando movimento da garra..."));

  int base = angG;
  for (int a = base; a >= constrain(base - 20, minG, maxG); a--) {
    sGarra.write(a); angG = a; delay(20);
  }
  delay(150);
  for (int a = angG; a <= constrain(base + 20, minG, maxG); a++) {
    sGarra.write(a); angG = a; delay(20);
  }
  delay(150);
  for (int a = angG; a >= base; a--) {
    sGarra.write(a); angG = a; delay(20);
  }
  Serial.println(F("[GARRA] Teste concluido."));
}

// Move para um ponto salvo sem iniciar o ciclo completo.
void testarPontoSalvo(const Ponto &p, const __FlashStringHelper *nome) {
  if (cicloEmExecucao) return;
  cicloEmExecucao = true;
  abortarCiclo = false;
  bufIdx = 0;
  Serial.print(F("[TESTE PONTO] Indo para "));
  Serial.println(nome);
  moverSuave(p.base, p.braco, p.cotovelo, p.garra, velocidadeMs);
  cicloEmExecucao = false;
  if (abortarCiclo) Serial.println(F("[MOVIMENTO] Teste do ponto interrompido."));
  else {
    Serial.print(F("[TESTE PONTO] Chegou ao "));
    Serial.println(nome);
  }
}

// Ciclo completo Estoque (Y) -> Esteira (X), com interrupção por STOP/FREE.
void executarCicloXY() {
  if (cicloEmExecucao) return;
  cicloEmExecucao = true;
  abortarCiclo = false;
  bufIdx = 0;
  Serial.println(F("[ARDUINO] Iniciando fluxo completo Y -> X. Envie STOP para interromper."));

  moverSuave(pontoY.base, 80, 80, angGarraAberta, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(150);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoY.base, pontoY.braco, pontoY.cotovelo, angGarraAberta, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(150);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoY.base, pontoY.braco, pontoY.cotovelo, angGarraFechada, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(300);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoY.base, 80, 80, angGarraFechada, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(150);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoX.base, 80, 80, angGarraFechada, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(150);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoX.base, pontoX.braco, pontoX.cotovelo, angGarraFechada, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(150);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoX.base, pontoX.braco, pontoX.cotovelo, angGarraAberta, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  aguardarCiclo(250);
  if (abortarCiclo) goto fimCiclo;

  moverSuave(pontoX.base, 80, 80, angGarraAberta, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  moverSuave(pontoNeutro.base, pontoNeutro.braco, pontoNeutro.cotovelo, pontoNeutro.garra, velocidadeMs);
  if (abortarCiclo) goto fimCiclo;
  Serial.println(F("[ARDUINO] Fluxo completo finalizado."));

fimCiclo:
  cicloEmExecucao = false;
  if (abortarCiclo) Serial.println(F("[CICLO] Abortado pelo usuário."));
}

// Bateria de testes automáticos completos para diagnosticar todos os braços
void executarTesteCompleto() {
  Serial.println(F("\n========================================"));
  Serial.println(F("[AUTO-TESTE] BATERIA COMPLETA DE DIAGNOSTICO"));
  Serial.println(F("========================================"));

  // 1. Pulso Isolado em cada motor
  Serial.println(F("[PASSO 1/5] Teste de Pulso Neutro Isolado (1500us centro):"));

  desenergizarServos();
  sBase.attach(PINO_BASE); sBase.writeMicroseconds(1500); delay(700); sBase.detach();
  Serial.println(F("  -> Base (10): Pulso OK"));

  sBraco.attach(PINO_BRACO); sBraco.writeMicroseconds(1500); delay(700); sBraco.detach();
  Serial.println(F("  -> Braco (11): Pulso OK"));

  sCotovelo.attach(PINO_COTOVELO); sCotovelo.writeMicroseconds(1500); delay(700); sCotovelo.detach();
  Serial.println(F("  -> Cotovelo (6): Pulso OK"));

  sGarra.attach(PINO_GARRA); sGarra.writeMicroseconds(1500); delay(700); sGarra.detach();
  Serial.println(F("  -> Garra (3): Pulso OK"));
  delay(600);

  // 2. Micro-passos no Pino 11 (Braço Direito)
  Serial.println(F("[PASSO 2/5] Micro-passos no Braco (11): 80 -> 95 -> 70 -> 80"));
  sBraco.attach(PINO_BRACO);
  for (int a = 80; a <= 95; a++) { sBraco.write(a); delay(25); }
  delay(300);
  for (int a = 95; a >= 70; a--) { sBraco.write(a); delay(25); }
  delay(300);
  for (int a = 70; a <= 80; a++) { sBraco.write(a); delay(25); }
  sBraco.detach();
  Serial.println(F("  -> Braco (11): Teste de passo finalizado"));
  delay(600);

  // 3. Varredura suave em cada eixo
  Serial.println(F("[PASSO 3/5] Varredura individual dos 4 motores:"));
  sBase.attach(PINO_BASE);
  for (int a = 90; a >= 45; a--) { sBase.write(a); delay(18); }
  for (int a = 45; a <= 135; a++) { sBase.write(a); delay(18); }
  for (int a = 135; a >= 90; a--) { sBase.write(a); delay(18); }
  sBase.detach();
  Serial.println(F("  -> Base: 45 a 135 OK"));

  sCotovelo.attach(PINO_COTOVELO);
  for (int a = 80; a >= 65; a--) { sCotovelo.write(a); delay(20); }
  for (int a = 65; a <= 95; a++) { sCotovelo.write(a); delay(20); }
  for (int a = 95; a >= 80; a--) { sCotovelo.write(a); delay(20); }
  sCotovelo.detach();
  Serial.println(F("  -> Cotovelo (6): 65 a 95 OK"));

  sGarra.attach(PINO_GARRA);
  for (int a = 80; a >= 50; a--) { sGarra.write(a); delay(18); }
  delay(300);
  for (int a = 50; a <= 100; a++) { sGarra.write(a); delay(18); }
  delay(300);
  for (int a = 100; a >= 80; a--) { sGarra.write(a); delay(18); }
  sGarra.detach();
  Serial.println(F("  -> Garra (3): Abre/Fecha OK"));
  delay(600);

  // 4. Teste Coordenado Braço 11 + Cotovelo 6
  Serial.println(F("[PASSO 4/5] Teste Coordenado (Braco 11 + Cotovelo 6):"));
  moverBracoJunto(75, 90); delay(700);
  moverBracoJunto(95, 75); delay(700);
  moverBracoJunto(80, 80); delay(500);
  sBraco.detach(); sCotovelo.detach();
  Serial.println(F("  -> Bracos coordenados OK"));
  delay(600);

  // 5. Simulação de Ciclo Industrial Completo
  Serial.println(F("[PASSO 5/5] Teste de Ciclo Completo (Estoque -> Esteira):"));
  executarCicloXY();

  desenergizarServos();
  Serial.println(F("========================================"));
  Serial.println(F("[FIM] Bateria Completa Concluida com Sucesso!"));
  Serial.println(F("Todos os motores estao DESENERGIZADOS por seguranca."));
  Serial.println(F("========================================"));
}

// =========================================================================
// 6. PROCESSADOR DE COMANDOS SERIAL
// =========================================================================
void processarComando(const char* cmd) {
  if (strlen(cmd) == 0) return;

  // Posição absoluta enviada pelo fluxo gravado na interface Web.
  if (strncmp(cmd, "POSE:", 5) == 0) {
    int baseVal = 0, bracoVal = 0, cotoveloVal = 0, garraVal = 0;
    if (sscanf(cmd + 5, "%d:%d:%d:%d", &baseVal, &bracoVal, &cotoveloVal, &garraVal) == 4) {
      cicloEmExecucao = true;
      abortarCiclo = false;
      moverSuave(baseVal, bracoVal, cotoveloVal, garraVal, velocidadeMs);
      cicloEmExecucao = false;
      Serial.println(abortarCiclo ? F("[POSE_ABORTED]") : F("[POSE_DONE]"));
    } else Serial.println(F("[ERRO] Use POSE:<base>:<ombro>:<cotovelo>:<garra>"));
    return;
  }

  if (strncmp(cmd, "SPEED:", 6) == 0) {
    int novaVelocidade = atoi(cmd + 6);
    if (novaVelocidade == 16 || novaVelocidade == 24 || novaVelocidade == 32) {
      velocidadeMs = novaVelocidade;
      Serial.print(F("[MOVIMENTO] Suavidade ajustada: "));
      Serial.print(velocidadeMs); Serial.println(F(" ms por grau."));
    } else Serial.println(F("[ERRO] Use SPEED:16, SPEED:24 ou SPEED:32."));
    return;
  }

  if (strcmp(cmd, "SEQSTART") == 0) {
    abortarCiclo = false;
    Serial.println(F("[SEQUENCE_READY]"));
    return;
  }

  if (strncmp(cmd, "SENSOR:", 7) == 0) {
    if (strcmp(cmd, "SENSOR:OFF") == 0) {
      sensorEnabled = false;
      sensorCandidate = false;
      sensorPresent = false;
      sensorClearSince = 0;
      salvarConfigSensor();
      Serial.println(F("[SENSOR] Desativado."));
      return;
    }
    int distancia = 0;
    unsigned long estabilidade = 0;
    if (sscanf(cmd + 7, "ON:%d:%lu", &distancia, &estabilidade) == 2 &&
        distancia >= 2 && distancia <= 100 &&
        (estabilidade == 3000 || estabilidade == 4000 || estabilidade == 5000)) {
      sensorDistanceCm = distancia;
      sensorStableMs = estabilidade;
      sensorEnabled = true;
      sensorCandidate = false;
      sensorPresent = false;
      sensorClearSince = 0;
      sensorLastReadAt = 0;
      salvarConfigSensor();
      Serial.print(F("[SENSOR] HC-SR04 ativo; distancia=")); Serial.print(sensorDistanceCm);
      Serial.print(F("cm; estabilidade=")); Serial.print(sensorStableMs / 1000); Serial.println(F("s."));
    } else Serial.println(F("[ERRO] Use SENSOR:ON:<distancia_cm 2-100>:<3000|4000|5000> ou SENSOR:OFF"));
    return;
  }

  // Restaura os limites amplos padrão caso uma faixa seja gravada por engano.
  if (strcmp(cmd, "LIMRESET") == 0) {
    minB = 0; maxB = 180;
    minBraco = 55; maxBraco = 180;
    minCotovelo = 55; maxCotovelo = 180;
    minG = 85; maxG = 180;
    salvarLimites();
    Serial.println(F("[LIMITE SALVO] Faixas amplas restauradas."));
    return;
  }

  // Movimento conjunto deve vir antes do despacho por eixo (ARM começa com A).
  if (strncmp(cmd, "ARM:", 4) == 0) {
    int bracoVal = 0, cotoveloVal = 0;
    if (sscanf(cmd + 4, "%d:%d", &bracoVal, &cotoveloVal) == 2) {
      moverBracoJunto(bracoVal, cotoveloVal);
    } else Serial.println(F("[ERRO] Use ARM:<braco>:<cotovelo>"));
    return;
  }

  // Salva os limites mecânicos escolhidos no calibrador web.
  if (strncmp(cmd, "LIM:", 4) == 0) {
    char eixoLim = 0;
    int novoMin = 0, novoMax = 0;
    if (sscanf(cmd + 4, "%c:%d:%d", &eixoLim, &novoMin, &novoMax) == 3) {
      if (!atualizarLimite(eixoLim, novoMin, novoMax)) Serial.println(F("[ERRO] Faixa de limite invalida."));
    } else Serial.println(F("[ERRO] Use LIM:<eixo>:<min>:<max>"));
    return;
  }

  // Salva ambos os limites da garra antes do despacho por eixo.
  if (strncmp(cmd, "GCALIB:", 7) == 0) {
    int ab = 0, fe = 0;
    if (sscanf(cmd + 7, "%d:%d", &ab, &fe) == 2) salvarGarraCalib(ab, fe);
    else Serial.println(F("[ERRO] Use GCALIB:<aberta>:<fechada>"));
    return;
  }

  char eixo = cmd[0];

  // 1. BASE (Pino 10)
  if (eixo == 'B') {
    if (strcmp(cmd, "B:FREE") == 0) {
      if (sBase.attached()) sBase.detach();
      Serial.println(F("[MOTOR] Base (10) DESLIGADA."));
    }
    else if (strcmp(cmd, "B:HOLD") == 0) {
      if (!sBase.attached()) { sBase.attach(PINO_BASE); sBase.write(angB); }
      Serial.println(F("[MOTOR] Base (10) ATIVA."));
    }
    else if (cmd[1] >= '0' && cmd[1] <= '9') {
      if (!sBase.attached()) sBase.attach(PINO_BASE);
      angB = constrain(atoi(cmd + 1), minB, maxB);
      sBase.write(angB);
    }
  }

  // 2. BRAÇO PRINCIPAL (Pino 11) - aceita 'A' (Arm) ou 'D'
  else if (eixo == 'A' || eixo == 'D') {
    if (strcmp(cmd, "A:FREE") == 0 || strcmp(cmd, "D:FREE") == 0) {
      if (sBraco.attached()) sBraco.detach();
      Serial.println(F("[MOTOR] Braco (11) DESLIGADO."));
    }
    else if (strcmp(cmd, "A:HOLD") == 0 || strcmp(cmd, "D:HOLD") == 0) {
      if (!sBraco.attached()) { sBraco.attach(PINO_BRACO); sBraco.write(angBraco); }
      Serial.println(F("[MOTOR] Braco (11) ATIVO."));
    }
    else if (strcmp(cmd, "A:TEST") == 0 || strcmp(cmd, "D:TEST") == 0) {
      diagnosticarPino11();
    }
    else if (cmd[1] >= '0' && cmd[1] <= '9') {
      if (!sBraco.attached()) sBraco.attach(PINO_BRACO);
      angBraco = constrain(atoi(cmd + 1), minBraco, maxBraco);
      sBraco.write(angBraco);
    }
  }

  // 3. COTOVELO COMPLEMENTAR (Pino 6) - aceita 'C' (Cotovelo) ou 'E'
  else if (eixo == 'C' || eixo == 'E') {
    if (strcmp(cmd, "C:FREE") == 0 || strcmp(cmd, "E:FREE") == 0) {
      if (sCotovelo.attached()) sCotovelo.detach();
      Serial.println(F("[MOTOR] Cotovelo (6) DESLIGADO (Seguro)."));
    }
    else if (strcmp(cmd, "C:HOLD") == 0 || strcmp(cmd, "E:HOLD") == 0) {
      if (!sCotovelo.attached()) { sCotovelo.attach(PINO_COTOVELO); sCotovelo.write(angCotovelo); }
      Serial.println(F("[MOTOR] Cotovelo (6) ATIVO."));
    }
    else if (cmd[1] >= '0' && cmd[1] <= '9') {
      if (!sCotovelo.attached()) sCotovelo.attach(PINO_COTOVELO);
      angCotovelo = constrain(atoi(cmd + 1), minCotovelo, maxCotovelo);
      sCotovelo.write(angCotovelo);
    }
  }

  // 5. GARRA (Pino 3)
  else if (eixo == 'G') {
    if (strcmp(cmd, "G:FREE") == 0 || strcmp(cmd, "G:OFF") == 0) {
      desenergizarGarra();
    }
    else if (strcmp(cmd, "G:HOLD") == 0 || strcmp(cmd, "G:ON") == 0) {
      energizarGarra();
    }
    else if (strcmp(cmd, "G:TEST") == 0 || strcmp(cmd, "TEST:G") == 0) {
      testarGarraLento();
    }
    else if (strcmp(cmd, "G:OPEN") == 0) {
      definirDestinoGarra(angGarraAberta, true);
      Serial.print(F("[GARRA] Abrindo suavemente a partir de ")); Serial.print(angG); Serial.println(F("°"));
    }
    else if (strcmp(cmd, "G:CLOSE") == 0) {
      definirDestinoGarra(angGarraFechada, true);
      Serial.print(F("[GARRA] Fechando suavemente a partir de ")); Serial.print(angG); Serial.println(F("°"));
    }
    else if (cmd[1] >= '0' && cmd[1] <= '9') {
      definirDestinoGarra(atoi(cmd + 1));
    }
  }

  // 7. CONTROLE GERAL DE ENERGIA DOS SERVOS
  else if (strcmp(cmd, "FREE") == 0 || strcmp(cmd, "DETACH") == 0) {
    desenergizarServos();
  }
  else if (strcmp(cmd, "HOLD") == 0 || strcmp(cmd, "ATTACH") == 0) {
    energizarServos();
  }

  // 8. MEMÓRIA EEPROM
  else if (strcmp(cmd, "Y") == 0 || strcmp(cmd, "SALVAR:ESTOQUE") == 0) {
    salvarPontoY();
  }
  else if (strcmp(cmd, "X") == 0 || strcmp(cmd, "SALVAR:ESTEIRA") == 0) {
    salvarPontoX();
  }
  else if (strcmp(cmd, "TESTY") == 0) {
    testarPontoSalvo(pontoY, F("ponto de pegar (Y)"));
  }
  else if (strcmp(cmd, "TESTX") == 0) {
    testarPontoSalvo(pontoX, F("ponto de entregar (X)"));
  }
  else if (strcmp(cmd, "N") == 0 || strcmp(cmd, "SALVAR:NEUTRO") == 0) {
    salvarPontoNeutro();
  }
  else if (strcmp(cmd, "TESTN") == 0) {
    testarPontoSalvo(pontoNeutro, F("ponto neutro"));
  }

  // Inicia o ciclo salvo; os testes de varredura continuam bloqueados.
  else if (strcmp(cmd, "RUN") == 0 || strcmp(cmd, "LOAD") == 0) {
    executarCicloXY();
  }
  else if (strcmp(cmd, "STOP") == 0) {
    abortarCiclo = true;
    desenergizarServos();
    Serial.println(F("[CICLO] Parado; servos soltos."));
  }
  else if (strcmp(cmd, "TESTALL") == 0 || strcmp(cmd, "AUTOTEST") == 0 || strcmp(cmd, "T") == 0 || strcmp(cmd, "TEST:11") == 0 || strcmp(cmd, "DIAG:11") == 0) {
    Serial.println(F("[BLOQUEADO] Varreduras automaticas desativadas."));
  }
  else if (strcmp(cmd, "H") == 0 || strcmp(cmd, "HOME") == 0) {
    Serial.println(F("[ARDUINO] Indo para Home neutra..."));
    moverSuave(pontoNeutro.base, pontoNeutro.braco, pontoNeutro.cotovelo, pontoNeutro.garra, velocidadeMs);
    Serial.println(F("[ARDUINO] Na Home."));
  }
  else if (strcmp(cmd, "?") == 0 || strcmp(cmd, "STATUS") == 0) {
    Serial.print(F("[STATUS] B:")); Serial.print(angB);
    Serial.print(F(" Braco(11):")); Serial.print(angBraco);
    Serial.print(F(" Cotovelo(6):")); Serial.print(angCotovelo);
    Serial.print(F(" Garra(3):")); Serial.print(angG);
    Serial.print(F(" | GarraAtiva: ")); Serial.println(garraAtiva ? F("SIM") : F("NAO"));
    imprimirPontos();
  }
}

// =========================================================================
// 7. SETUP
// =========================================================================
void setup() {
  Serial.begin(9600);
  pinMode(PINO_SENSOR_TRIG, OUTPUT);
  pinMode(PINO_SENSOR_ECHO, INPUT);
  digitalWrite(PINO_SENSOR_TRIG, LOW);

  // Mantém os servos soltos no boot; cada eixo energiza ao receber comando.
  Serial.println(F("[ARDUINO] Calibrador manual MeArm pronto."));
  carregarMemoria();
  Serial.println(F("[ARDUINO] Pronto para calibracao Web manual!"));
  carregarConfigSensor();
}

// =========================================================================
// 8. LOOP (Não-bloqueante com descarte em overflow)
// =========================================================================
void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (bufIdx > 0) {
        serialBuf[bufIdx] = '\0';
        processarComando(serialBuf);
        bufIdx = 0;
      }
    }
    else {
      if (bufIdx < sizeof(serialBuf) - 1) {
        serialBuf[bufIdx++] = c;
      } else {
        bufIdx = 0;
      }
    }
  }
  atualizarGarraSuave();
  monitorarSensor();
}
