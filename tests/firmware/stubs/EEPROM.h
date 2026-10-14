#pragma once
#include "Arduino.h"
struct HostEEPROM {
  // Registros tipados por endereco: o host tem int de 32 bits e o AVR de 16.
  // O layout binario AVR e verificado por static_assert no proprio sketch.
  std::map<int, std::vector<byte>> records;
  template<class T> void put(int address, const T &value) {
    const byte *start = reinterpret_cast<const byte *>(&value);
    records[address] = std::vector<byte>(start, start + sizeof(T));
  }
  template<class T> void get(int address, T &value) {
    auto found = records.find(address);
    if (found == records.end() || found->second.size() != sizeof(T)) std::memset(&value, 0xFF, sizeof(T));
    else std::memcpy(&value, found->second.data(), sizeof(T));
  }
};
inline HostEEPROM EEPROM;
