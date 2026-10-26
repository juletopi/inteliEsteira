#pragma once
// Testes de comportamento do sketch no host; nao simula eletrica ou dinamica.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <sstream>
#include <string>
#include <vector>
using byte = uint8_t;
class __FlashStringHelper;
#define F(s) reinterpret_cast<const __FlashStringHelper *>(s)
#define pgm_read_byte(p) (*(p))
#define PSTR(s) (s)
#define strcmp_P strcmp
#define strncmp_P strncmp
#define sscanf_P sscanf
constexpr int LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2, NUM_DIGITAL_PINS = 20;
inline uint32_t hostMillis = 0;
inline std::function<void()> hostOnDelay;
inline std::vector<std::string> hostEvents;
inline std::map<int, int> hostPins;
inline unsigned long hostEcho = 0;
inline unsigned long millis() { return hostMillis; }
inline void delay(unsigned long ms) { hostMillis += ms; if (hostOnDelay) hostOnDelay(); }
inline void delayMicroseconds(unsigned long us) { hostMillis += us / 1000; }
inline void pinMode(int pin, int mode) { if (mode == INPUT_PULLUP && !hostPins.count(pin)) hostPins[pin] = HIGH; }
inline void digitalWrite(int pin, int value) { hostPins[pin] = value; }
inline int digitalRead(int pin) { return hostPins.count(pin) ? hostPins[pin] : HIGH; }
inline unsigned long pulseIn(int, int, unsigned long) { return hostEcho; }
inline bool isDigit(char c) { return c >= '0' && c <= '9'; }
inline bool isAlphaNumeric(char c) { return std::isalnum(static_cast<unsigned char>(c)); }
using std::min;
using std::max;
template<class T, class A, class B> T constrain(T value, A low, B high) {
  return value < low ? static_cast<T>(low) : value > high ? static_cast<T>(high) : value;
}
struct HostSerial {
  std::deque<char> input;
  std::string output, currentLine;
  void begin(int) {}
  int available() { return static_cast<int>(input.size()); }
  char read() { char c = input.front(); input.pop_front(); return c; }
  void feed(const std::string &s) { for (char c : s) input.push_back(c); }
  template<class T> void print(const T &value) { std::ostringstream s; s << value; append(s.str()); }
  void print(const __FlashStringHelper *value) { append(reinterpret_cast<const char *>(value)); }
  void print(byte value) { print(static_cast<int>(value)); }
  template<class T> void println(const T &value) { print(value); println(); }
  void println() { append("\n"); }
  void append(const std::string &value) {
    output += value;
    for (char c : value) {
      if (c == '\n') { hostEvents.push_back(currentLine); currentLine.clear(); }
      else currentLine += c;
    }
  }
  void clear() { output.clear(); currentLine.clear(); hostEvents.clear(); }
};
inline HostSerial Serial;
