#!/usr/bin/env pybricks-micropython
# -*- coding: utf-8 -*-

"""
PROJETO: Esteira Seletora Inteligente
DISCENTE: Wasgton Gomes Pereira
DESCRIÇÃO: Módulo de acionamento de motores da esteira separadora baseado em
           parâmetros de calibração por região (codR).

Integracao: calibracoes preservadas em calibration.py; movimento nao bloqueante
para permitir receber STOP e detectar perda de comunicacao durante o transporte.
Este modulo roda no EV3, nunca dentro do Flask no computador.
"""

try:
    from .calibration import get_calibration
except ImportError:
    from calibration import get_calibration


class EV3Motion:
    def __init__(self, motor_a=None, motor_c=None, clock=None, hold=None):
        # Imports locais permitem testar as mesmas sequencias sem o EV3.
        if motor_a is None or motor_c is None:
            from pybricks.hubs import EV3Brick
            from pybricks.ev3devices import Motor
            from pybricks.parameters import Port, Stop
            from pybricks.tools import StopWatch

            self.ev3 = EV3Brick()
            motor_a = Motor(Port.A)  # Tracao da esteira.
            motor_c = Motor(Port.C)  # Separador.
            watch = StopWatch()
            clock = watch.time
            hold = Stop.HOLD
        else:
            self.ev3 = None
        self.motor_a = motor_a
        self.motor_c = motor_c
        self.clock = clock
        self.hold = hold
        self.stage = None
        self.started_at = 0
        self.pause_until = 0
        self.calibration = None

    def start(self, code):
        if self.stage is not None:
            raise RuntimeError("Ja existe um movimento ativo.")
        self.calibration = get_calibration(code)
        name, scale_a, turns_a, _scale_c, _turns_c = self.calibration
        print("Região localizada:", name)
        self.started_at = self.clock()
        self.stage = "A"
        self.motor_a.run_angle(
            speed=scale_a * 10,
            rotation_angle=turns_a * 360,
            then=self.hold,
            wait=False,
        )

    def poll(self):
        """Retorna True apenas quando a sequencia calibrada terminou."""
        if self.stage is None:
            return False
        now = self.clock()
        if now - self.started_at >= 30000:
            self.stop()
            raise RuntimeError("MOTION_TIMEOUT")
        if self.stage == "A" and self.motor_a.control.done():
            self.stage = "PAUSA"
            self.pause_until = now + 300
        if self.stage == "PAUSA" and now >= self.pause_until:
            _name, _scale_a, _turns_a, scale_c, turns_c = self.calibration
            if turns_c == 0:
                self.stage = None
                return True
            self.stage = "C"
            self.motor_c.run_angle(
                speed=scale_c * 10,
                rotation_angle=turns_c * 360,
                then=self.hold,
                wait=False,
            )
        if self.stage == "C" and self.motor_c.control.done():
            self.stage = None
            return True
        return False

    def stop(self):
        self.stage = None
        # Tenta frear ambos mesmo se um dos motores falhar.
        try:
            self.motor_a.brake()
        finally:
            self.motor_c.brake()


def acionar_esteira(codR):
    """Teste manual original, com as mesmas velocidades, voltas e pausa."""
    from pybricks.tools import wait

    get_calibration(codR)
    motion = EV3Motion()
    try:
        motion.start(codR)
        while not motion.poll():
            wait(20)
        motion.ev3.speaker.beep(frequency=1000, duration=100)
    except BaseException:
        motion.stop()
        raise


if __name__ == "__main__":
    try:
        acionar_esteira(int(input("Digite o código da região (1 a 10): ")))
    except ValueError:
        print("Código de região não localizado")
