#pragma once

// Sensores DIGITAIS por saida R01..R10, independentes do HC-SR04 de presenca.
// -1 = nao instalado. Nunca use os pinos dos servos, da serial ou do HC-SR04.
#ifndef INTELIESTEIRA_ARRIVAL_PINS
#define INTELIESTEIRA_ARRIVAL_PINS {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1}
#endif
const int BACKEND_ARRIVAL_PINS[10] = INTELIESTEIRA_ARRIVAL_PINS;
const bool BACKEND_SENSOR_ACTIVE_LOW = true;
const unsigned long BACKEND_DEBOUNCE_MS = 30;
const unsigned long BACKEND_WATCHDOG_MS = 4000;
const unsigned long BACKEND_ACTION_TIMEOUT_MS = 25000;
