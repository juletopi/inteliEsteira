class Arduino:
    def connect(self):
        # TODO: abrir a porta serial usando config.ARDUINO_PORT e baudrate.
        raise NotImplementedError

    def disconnect(self):
        # TODO: fechar a porta serial de forma segura.
        raise NotImplementedError

    def send_command(self, command):
        # TODO: implementar o protocolo semântico Python <-> Arduino.
        # TODO: aceitar comandos como GARRA:PEGAR e ESTEIRA:START.
        raise NotImplementedError

    def read_response(self):
        # TODO: ler e interpretar respostas OK:* e ERRO:*.
        raise NotImplementedError

    def is_connected(self):
        # TODO: retornar o estado real da conexão serial.
        raise NotImplementedError
