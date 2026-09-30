#!/usr/bin/env pybricks-micropython
# -*- coding: utf-8 -*-

"""
PROJETO: Esteira Seletora Inteligente
DISCENTE: Wasgton Gomes Pereira
DESCRIÇÃO: Módulo de acionamento de motores da esteira separadora baseado em
           parâmetros de calibração por região (codR).
"""

from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor
from pybricks.parameters import Port, Stop
from pybricks.tools import wait

# ==============================================================================
# INICIALIZAÇÃO DO HARDWARE (BLOCO EV3 E MOTORES)
# ==============================================================================
ev3 = EV3Brick()

# Instanciação dos motores conforme mapeamento de portas do EV3:
# Motor A -> Tração e avanço longitudinal da esteira
# Motor C -> Braço empurrador/separador de cargas
motorA = Motor(Port.A)
motorC = Motor(Port.C)

# ==============================================================================
# FUNÇÃO PRINCIPAL DE ACIONAMENTO DA ESTEIRA
# ==============================================================================
def acionar_esteira(codR):
    """
    Recebe o código numérico da região (codR de 1 a 10) e atribui a força
    e rotação específicas para os Motores A e C com base na tabela de calibração.
    """

    # --- ESTRUTURA CONDICIONAL DE SELEÇÃO DE REGIÃO ---
    if codR == 1:
        regiao = "Norte 1"
        forcaA = 12; rotacaoA = 0.7; forcaC = 20; rotacaoC = -1.0

    elif codR == 2:
        regiao = "Norte 2"
        forcaA = 12; rotacaoA = 0.3; forcaC = 20; rotacaoC = -1.0

    elif codR == 3:
        regiao = "Nordeste 1"
        forcaA = 12; rotacaoA = 1.85; forcaC = 20; rotacaoC = -1.0

    elif codR == 4:
        regiao = "Nordeste 2"
        forcaA = 12; rotacaoA = 1.47; forcaC = 20; rotacaoC = -1.0

    elif codR == 5:
        regiao = "Centro-Oeste 1"
        forcaA = 12; rotacaoA = 1.47; forcaC = 20; rotacaoC = 1.0

    elif codR == 6:
        regiao = "Centro-Oeste 2"
        forcaA = 12; rotacaoA = 1.85; forcaC = 20; rotacaoC = 1.0

    elif codR == 7:
        regiao = "Sudoeste 1"
        forcaA = 12; rotacaoA = 0.3; forcaC = 20; rotacaoC = 1.0

    elif codR == 8:
        regiao = "Sudoeste 2"
        forcaA = 12; rotacaoA = 0.7; forcaC = 20; rotacaoC = 1.0

    elif codR == 9:
        regiao = "Sul 1"
        forcaA = 12; rotacaoA = 2.3; forcaC = 20; rotacaoC = 0.0

    elif codR == 10:
        regiao = "Sul 2"
        forcaA = 12; rotacaoA = -1.0; forcaC = 20; rotacaoC = 0.0

    else:
        # Tratamento de erro caso o código informado não exista na tabela
        print("Código de região não localizado")
        ev3.speaker.beep(frequency=200, duration=500)
        return

    # [OPCIONAL / TESTE]: Exibe a região localizada no terminal durante testes manuais
    print("Região localizada:", regiao)

    # --- CONVERSÃO DE PARÂMETROS PARA SINAIS DO EV3 ---
    # Força (%) convertida para velocidade angular (deg/s)
    # Rotações (voltas completas) convertidas para graus de rotação (1 volta = 360°)
    velA = forcaA * 10
    grausA = rotacaoA * 360

    velC = forcaC * 10
    grausC = rotacaoC * 360

    # --- EXECUÇÃO FÍSICA DOS MOTORES ---
    # 1. Acionamento do Motor A (Giro/Avanço da esteira principal)
    if grausA != 0:
        motorA.run_angle(speed=velA, rotation_angle=grausA, then=Stop.HOLD)

    wait(300) # Pausa técnica para estabilização do pacote na esteira

    # 2. Acionamento do Motor C (Mecanismo empurrador/separador)
    if grausC != 0:
        motorC.run_angle(speed=velC, rotation_angle=grausC, then=Stop.HOLD)

    # Sinal sonoro indicando fim do ciclo de triagem da encomenda
    ev3.speaker.beep(frequency=1000, duration=100)


# ==============================================================================
# BLOCO DE TESTE MANUAM / LOCAL (APENAS PARA EXECUÇÃO VIA TERMINAL)
# Nota: Este bloco é ignorado quando a função acionar_esteira() for importada
# por outro módulo do projeto (ex: script de leitura de QR Code/Visão Computacional).
# ==============================================================================
if __name__ == "__main__":
    try:
        # Solicita dinamicamente a entrada do código da região via terminal SSH
        entrada = input("Digite o código da região (1 a 10): ")
        codigo_digitado = int(entrada)

        # Chamada da função passando o parâmetro coletado
        acionar_esteira(codR=codigo_digitado)

    except ValueError:
        print("Código de região não localizado")
