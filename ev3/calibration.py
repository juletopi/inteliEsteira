"""Calibracoes de Wasgton Gomes Pereira; valores recebidos sem alteracao.

Os dois destinos chamados 'Sudoeste' no original correspondem ao Sudeste.
O fator de velocidade 10 e uma escala do projeto, nao uma conversao de torque.
Modulo compativel com CPython e EV3 MicroPython, sem inicializar motores.
"""

# codR: (nome, escalaA, voltasA, escalaC, voltasC)
CALIBRATIONS = {
    1: ("Norte 1", 12, 0.7, 20, -1.0),
    2: ("Norte 2", 12, 0.3, 20, -1.0),
    3: ("Nordeste 1", 12, 1.85, 20, -1.0),
    4: ("Nordeste 2", 12, 1.47, 20, -1.0),
    5: ("Centro-Oeste 1", 12, 1.47, 20, 1.0),
    6: ("Centro-Oeste 2", 12, 1.85, 20, 1.0),
    7: ("Sudeste 1", 12, 0.3, 20, 1.0),
    8: ("Sudeste 2", 12, 0.7, 20, 1.0),
    9: ("Sul 1", 12, 2.3, 20, 0.0),
    10: ("Sul 2", 12, -1.0, 20, 0.0),
}

# A numeracao do backend NAO coincide com a numeracao local do EV3.
DESTINATION_TO_CODE = {
    "R01": 1, "R02": 2,
    "R03": 9, "R04": 10,
    "R05": 7, "R06": 8,
    "R07": 3, "R08": 4,
    "R09": 5, "R10": 6,
}


def get_calibration(code):
    if code not in CALIBRATIONS:
        raise ValueError("Codigo de regiao nao localizado.")
    return CALIBRATIONS[code]
