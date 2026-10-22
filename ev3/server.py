#!/usr/bin/env pybricks-micropython
"""Ponte TCP a executar NO EV3. O Flask e o banco continuam no computador."""

try:
    import usocket as socket
except ImportError:
    import socket

# MicroPython pode nao definir __package__ ao executar um arquivo diretamente.
if globals().get("__package__"):
    from .bridge import BridgeController
else:
    from bridge import BridgeController


def validate_token(token):
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not 16 <= len(token) <= 128 or any(c not in alphabet for c in token):
        raise ValueError("Token deve conter 16 a 128 letras, numeros, '_' ou '-'.")


def default_clock():
    try:
        from time import monotonic
        return monotonic
    except ImportError:
        from pybricks.tools import StopWatch
        watch = StopWatch()
        return lambda: watch.time() / 1000.0


def send_bytes(connection, payload):
    """Envia todos os bytes sem depender de socket.sendall (ausente no EV3)."""
    while payload:
        sent = connection.send(payload)
        if sent is None or sent <= 0:
            raise OSError("SOCKET_SEND_FAILED")
        payload = payload[sent:]


def receive_timed_out(error):
    timeout_type = getattr(socket, "timeout", None)
    if timeout_type is not None and isinstance(error, timeout_type):
        return True
    # MicroPython sinaliza timeout como OSError com errno; Windows pode usar
    # WSAEWOULDBLOCK/WSAETIMEDOUT. Reset e descritor fechado sao falhas reais.
    code = getattr(error, "errno", None)
    if code is None and error.args:
        code = error.args[0]
    return code in (11, 110, 10035, 10060)


def serve_client(connection, bridge, token, *, clock=None, watchdog=4.0):
    """Uma sessao, um controller e polling de movimento a cada 20 ms."""
    validate_token(token)
    clock = clock or default_clock()
    # O MicroPython do EV3 nao implementa select.select. Um timeout curto no
    # proprio socket permite receber comandos e continuar consultando o motor.
    connection.settimeout(0.02)
    buffer = b""
    authenticated = False
    last_received = clock()
    try:
        while clock() - last_received < watchdog:
            try:
                data = connection.recv(512)
            except OSError as error:
                if not receive_timed_out(error):
                    raise
                data = None
            if data == b"":
                return
            if data:
                buffer += data
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if len(raw) > 512:
                        raise ValueError("FRAME_TOO_LONG")
                    line = raw.decode("utf-8").strip()
                    if not authenticated:
                        if line != "AUTH:" + token:
                            send_bytes(connection, b"ERROR:AUTH\n")
                            return
                        authenticated = True
                        responses = ["READY:EV3"]
                    elif line == "PING":
                        responses = ["PONG"]
                    else:
                        responses = bridge.handle(line)
                    last_received = clock()
                    for response in responses:
                        send_bytes(connection, (response + "\n").encode("utf-8"))
                if len(buffer) > 512:
                    raise ValueError("FRAME_TOO_LONG")
            if authenticated:
                for response in bridge.poll():
                    send_bytes(connection, (response + "\n").encode("utf-8"))
    finally:
        try:
            if authenticated:
                bridge.connection_lost()
        finally:
            connection.close()


def run_server(motion, token, host="0.0.0.0", port=8765):
    validate_token(token)
    bridge = BridgeController(motion)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_REUSEADDR"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
        listener.bind(address)
        listener.listen(1)
        print("EV3 aguardando backend em", host, port)
        while True:
            connection, _address = listener.accept()
            try:
                serve_client(connection, bridge, token)
            except (OSError, ValueError, RuntimeError):
                # Nao imprime frames nem o token de autenticacao.
                print("Sessao encerrada; confira conexao, motores e reset.")
    finally:
        try:
            motion.stop()
        finally:
            listener.close()


if __name__ == "__main__":
    import sys
    from main import EV3Motion

    # Arquivo local ignorado pelo Git. Execute a partir da pasta ev3/.
    with open("token.txt", "r") as token_file:
        shared_token = token_file.read().strip()
    bind_host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    bind_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    validate_token(shared_token)
    run_server(EV3Motion(), shared_token, bind_host, bind_port)
