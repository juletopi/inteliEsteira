"""Compila e executa o sketch MeArm no host com EEPROM/servos simulados."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("unvalidated", "cycle", "retry", "stop", "reset_moving", "watchdog", "timeout",
             "order", "invalidate", "corrupt", "persist", "presence", "manual", "overflow", "missing_sensor",
             "sensor_blocked", "sensor_arrival", "early_sensor")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", help="Caminho para g++, clang++ ou zig.")
    args = parser.parse_args()
    compiler = args.compiler or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        parser.error("Informe --compiler com um compilador C++17 (g++, clang++ ou zig).")
    output = ROOT / "output" / "firmware-native"
    output.mkdir(parents=True, exist_ok=True)
    executable = output / ("test_mearm.exe" if os.name == "nt" else "test_mearm")
    command = [compiler]
    if Path(compiler).stem.lower() == "zig":
        command.append("c++")
    command.extend(["-std=c++17", "-I", str(ROOT / "tests/firmware/stubs"),
                    str(ROOT / "tests/firmware/test_mearm.cpp"), "-o", str(executable)])
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache/global"),
               ZIG_LOCAL_CACHE_DIR=str(output / "cache/local"))
    subprocess.run(command, env=env, cwd=ROOT, check=True, timeout=300)
    for scenario in SCENARIOS:
        subprocess.run([str(executable), scenario], cwd=ROOT, check=True, timeout=10)
    print(f"OK: {len(SCENARIOS)} cenarios do sketch real no host; sem validacao eletrica/mecanica.")


if __name__ == "__main__":
    main()
