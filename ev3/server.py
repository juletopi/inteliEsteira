#!/usr/bin/env pybricks-micropython
"""Ponte TCP a executar NO EV3. O Flask e o banco continuam no computador."""

try:
    import usocket as socket
    import uselect as select
except ImportError:
    import socket
    import select

try:
    from .bridge import BridgeController
except ImportError:
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


def serve_client(connection, bridge, token, *, clock=None, watchdog=4.0):
    """Uma sessao, um controller e polling de movimento a cada 20 ms."""
    validate_token(token)
    clock = clock or default_clock()
    connection.settimeout(0.2)
    buffer = b""
    authenticated = False
    last_received = clock()
    try:
        while clock() - last_received < watchdog:
            readable, _writable, _exceptional = select.select([connection], [], [], 0.02)
            if readable:
                data = connection.recv(512)
                if not data:
                    return
                buffer += data
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    if len(raw) > 512:
                        raise ValueError("FRAME_TOO_LONG")
                    line = raw.decode("utf-8").strip()
                    if not authenticated:
                        if line != "AUTH:" + token:
                            connection.sendall(b"ERROR:AUTH\n")
                            return
                        authenticated = True
                        responses = ["READY:EV3"]
                    elif line == "PING":
                        responses = ["PONG"]
                    else:
                        responses = bridge.handle(line)
                    last_received = clock()
                    for response in responses:
                        connection.sendall((response + "\n").encode("utf-8"))
                if len(buffer) > 512:
                    raise ValueError("FRAME_TOO_LONG")
            if authenticated:
                for response in bridge.poll():
                    connection.sendall((response + "\n").encode("utf-8"))
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
