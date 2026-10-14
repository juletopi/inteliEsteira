#pragma once
#include "Arduino.h"
struct Servo {
  bool active = false;
  int pin = -1, angle = 90;
  int attach(int p) { pin = p; active = true; hostEvents.push_back("ATTACH"); return 1; }
  void detach() { active = false; }
  bool attached() const { return active; }
  void write(int value) { angle = value; hostEvents.push_back("SERVO:" + std::to_string(pin) + ":" + std::to_string(value)); }
  void writeMicroseconds(int value) { write(value); }
};
