"""Perfil versionado da trajetória MeArm usada pelo calibrador e pelo automático."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class GripperProfileError(ValueError):
    pass


def normalize_profile(payload):
    if not isinstance(payload, dict):
        raise GripperProfileError("O perfil de movimento precisa ser um objeto JSON.")
    pickup = _normalize_steps(payload.get("pickup"), "pegar")
    delivery = _normalize_steps(payload.get("delivery"), "entregar")
    neutral = _normalize_pose(payload.get("neutral"), "neutro")
    if not pickup or not delivery:
        raise GripperProfileError("O perfil precisa ter passos para pegar e entregar.")
    if any(delivery[-1][axis] != neutral[axis] for axis in ("B", "A", "C", "G")):
        raise GripperProfileError("O último passo de entrega precisa terminar no ponto neutro.")

    speed = _integer(payload.get("motion_delay_ms", payload.get("motionDelayMs", 24)), "velocidade")
    if speed not in {16, 24, 32}:
        raise GripperProfileError("A velocidade deve ser 16, 24 ou 32 ms por grau.")
    repeat = payload.get("repeat", True)
    if not isinstance(repeat, bool):
        raise GripperProfileError("A opção de repetição precisa ser booleana.")
    sensor = payload.get("sensor") if isinstance(payload.get("sensor"), dict) else {}
    distance = _integer(sensor.get("distance_cm", sensor.get("distanceCm", 10)), "distância do sensor")
    stable = _integer(sensor.get("stable_ms", sensor.get("stableMs", 4000)), "estabilidade do sensor")
    if not 2 <= distance <= 100 or stable not in {3000, 4000, 5000}:
        raise GripperProfileError("Configure o sensor entre 2 e 100 cm e estabilidade de 3, 4 ou 5 segundos.")
    gripper = payload.get("gripper") if isinstance(payload.get("gripper"), dict) else {}
    opened = _integer(gripper.get("open", payload.get("grip_open", 158)), "abertura da garra")
    closed = _integer(gripper.get("closed", payload.get("grip_closed", 86)), "fechamento da garra")
    if not (85 <= opened <= 180 and 85 <= closed <= 180 and opened != closed):
        raise GripperProfileError("Os ângulos de abertura e fechamento da garra são inválidos.")

    normalized = {
        "schema_version": 1,
        "source": str(payload.get("source", "calibracao-web"))[:80],
        "pickup": pickup,
        "delivery": delivery,
        "neutral": neutral,
        "repeat": repeat,
        "motion_delay_ms": speed,
        "sensor": {"enabled": bool(sensor.get("enabled", True)), "distance_cm": distance, "stable_ms": stable},
        "gripper": {"open": opened, "closed": closed},
    }
    normalized["version"] = profile_version(normalized)
    return normalized


def profile_version(profile):
    stable = {key: value for key, value in profile.items() if key != "version"}
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _normalize_steps(value, label):
    if not isinstance(value, list) or len(value) > 20:
        raise GripperProfileError(f"A etapa “{label}” deve conter de 1 a 20 passos.")
    steps = []
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            raise GripperProfileError(f"Passo {index} de “{label}” inválido.")
        pose = _normalize_pose(raw, f"passo {index} de {label}")
        pause = _integer(raw.get("pause_ms", raw.get("pauseMs", 0)), f"pausa do passo {index}")
        if not 0 <= pause <= 10000:
            raise GripperProfileError(f"A pausa do passo {index} deve ficar entre 0 e 10000 ms.")
        name = str(raw.get("name", f"{label.title()} {index}")).strip()[:64]
        if not name:
            name = f"{label.title()} {index}"
        steps.append({"name": name, **pose, "pause_ms": pause})
    return steps


def _normalize_pose(value, label):
    if not isinstance(value, dict):
        raise GripperProfileError(f"Defina os quatro ângulos de {label}.")
    pose = {}
    aliases = {"B": ("B", "base_graus"), "A": ("A", "ombro_graus"),
               "C": ("C", "cotovelo_graus"), "G": ("G", "garra_graus")}
    for axis, keys in aliases.items():
        raw = next((value[key] for key in keys if key in value), None)
        angle = _integer(raw, f"ângulo {axis} de {label}")
        if not 0 <= angle <= 180:
            raise GripperProfileError(f"Ângulo {axis} de {label} fora de 0–180 graus.")
        pose[axis] = angle
    return pose


def _integer(value, label):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise GripperProfileError(f"Valor inválido para {label}.") from exc
    if isinstance(value, bool) or str(number) != str(value).strip():
        raise GripperProfileError(f"Valor inválido para {label}.")
    return number


class GripperProfileStore:
    def __init__(self, default_path, local_path):
        self.default_path = Path(default_path)
        self.local_path = Path(local_path)

    def load(self):
        path = self.local_path if self.local_path.exists() else self.default_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GripperProfileError(f"Não foi possível carregar o perfil {path.name}: {exc}.") from exc
        return normalize_profile(data)

    def save(self, payload):
        profile = normalize_profile(payload)
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.local_path.parent,
                                prefix=f".{self.local_path.name}.", suffix=".tmp", delete=False) as temp:
            temp.write(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
            temp_path = Path(temp.name)
        try:
            os.replace(temp_path, self.local_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return profile

    def source(self):
        return "personalizado" if self.local_path.exists() else "oficial"
