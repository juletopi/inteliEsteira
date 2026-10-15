"""Painel com Arduino e EV3 virtuais: python -m scripts.bancada."""

import argparse
from contextlib import contextmanager
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep

from app import create_app
from ev3.simulator import EV3Simulator
from hardware.serial_simulator import ProtocolSimulator


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = [("TESTE-AM", "AM"), ("TESTE-PR", "PR"), ("TESTE-SP", "SP"),
            ("TESTE-CE", "CE"), ("TESTE-GO", "GO")]


@contextmanager
def virtual_bench(database, *, camera="mock", arduino_options=None):
    token = secrets.token_hex(16)
    arduino = ProtocolSimulator(("127.0.0.1", 0), delay=0.03, **(arduino_options or {}))
    ev3 = EV3Simulator(token=token, delay=0.03)
    servers = (arduino, ev3)
    threads = []
    app = None
    try:
        for server in servers:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            threads.append(thread)
        app = create_app({
            "AUTO_OPERATION": False, "EV3_IS_SIMULATED": True,
            "DATABASE_PATH": Path(database), "BOOTSTRAP_CATALOG": False,
            "HARDWARE_MODE": "simulator", "ARDUINO_SIMULATOR_PORT": arduino.server_address[1],
            "CONVEYOR_MODE": "ev3", "EV3_HOST": "127.0.0.1",
            "EV3_PORT": ev3.server_address[1], "EV3_TOKEN": token,
            "CAMERA_MODE": camera, "ARRIVAL_SENSOR_MODE": "arduino",
            # Esta bancada cria ambos os dispositivos em localhost, sem hardware.
            "REQUIRE_PHYSICAL_ARRIVAL": False, "GRIPPER_PROFILE_CALIBRATED": False,
        })
        client = app.test_client()
        products = app.extensions["product_repository"]
        for product, uf in PRODUCTS:
            if products.get(product, include_inactive=True) is None:
                response = client.post("/api/products", json={"produto_id": product, "uf": uf})
                if response.status_code != 201:
                    raise RuntimeError(response.get_json())
            response = client.post(f"/api/products/{product}/aruco")
            if response.status_code != 200:
                raise RuntimeError(response.get_json())
        yield app, arduino, ev3
    finally:
        if app is not None:
            app.extensions["workflow"].shutdown()
            for key in ("arduino", "conveyor_device", "camera"):
                app.extensions[key].disconnect()
        for server, thread in zip(servers, threads):
            server.shutdown()
            thread.join(timeout=2)
        for server in servers:
            server.server_close()


def request_ok(client, path, **kwargs):
    response = client.post(path, **kwargs)
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"{path}: {response.get_json()}")
    return response.get_json()


def wait_for(app, predicate, timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = app.extensions["workflow"].snapshot()
        if snapshot["fluxo"].get("erro"):
            raise RuntimeError(snapshot)
        if predicate(snapshot):
            return
        sleep(0.02)
    raise TimeoutError(app.extensions["workflow"].snapshot())


def smoke_test(app, arduino, ev3):
    """Exercita os dez destinos pela API e pelos dois sockets, sem motores."""
    client = app.test_client()
    planned = [product for product, _uf in PRODUCTS for _unit in range(2)]
    request_ok(client, "/api/flow/start")
    for index, product in enumerate(planned, start=1):
        wait_for(app, lambda snapshot: snapshot["proxima_caixa_liberada"])
        request_ok(client, "/api/simulation/presence", json={"presente": False})
        request_ok(client, "/api/simulation/camera", json={"produto_id": product})
        request_ok(client, "/api/simulation/presence", json={"presente": True})
        wait_for(app, lambda snapshot: app.extensions["cycle_repository"].count_completed() == index and snapshot["proxima_caixa_liberada"])
    app.extensions["workflow"].shutdown()
    cycles = app.extensions["cycle_repository"].list_recent(20)
    if {cycle["destino"] for cycle in cycles} != {f"R{i:02}" for i in range(1, 11)}:
        raise AssertionError(cycles)
    if any(cycle["estado"] != "FINALIZADO" for cycle in cycles) or len(ev3.motion.codes) != 10:
        raise AssertionError(cycles)
    for cycle in cycles:
        stored = app.extensions["cycle_repository"].get(cycle["id"], include_events=True)
        arrivals = [event for event in stored["eventos"] if event["tipo"] == "DESTINO_ALCANCADO"]
        if len(arrivals) != 1 or arrivals[0]["dados"].get("fisica") is not False:
            raise AssertionError("Simulacao sem comprovacao ou registrada como chegada fisica.")
    print("OK: 10 ciclos automaticos, 10 destinos, HC-SR04 antes da coleta, leitura na esteira, Arduino e EV3 via TCP; chegada SIMULADA.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", choices=("mock", "opencv"), default="mock")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--database", type=Path, help="Banco persistente exclusivo da bancada (opcional).")
    args = parser.parse_args()
    if args.smoke_test and args.camera != "mock":
        parser.error("--smoke-test usa camera mock; teste ArUco com --camera opencv no painel.")
    if args.smoke_test and args.database is not None:
        parser.error("--smoke-test usa somente banco temporario para nao interferir nos seus dados.")
    if args.database is not None and args.database.resolve() == (ROOT / "data" / "inteliesteira.db").resolve():
        parser.error("Use um banco separado do banco principal data/inteliesteira.db.")
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="bancada-", dir=output) as folder:
        database = args.database.resolve() if args.database else Path(folder) / "bancada.db"
        with virtual_bench(database, camera=args.camera) as (app, arduino, ev3):
            if args.smoke_test:
                smoke_test(app, arduino, ev3)
            else:
                request_ok(app.test_client(), "/api/flow/start")
                print(f"BANCADA VIRTUAL: http://127.0.0.1:{args.port} — sem motores reais.", flush=True)
                print(f"Banco {'persistente' if args.database else 'temporario'}: {database}", flush=True)
                print("Produtos TESTE-AM/PR/SP/CE/GO. Camera mock: use Simular leitura no painel.", flush=True)
                app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
