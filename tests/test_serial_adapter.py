from queue import Empty, Queue
from threading import Event, Thread
import unittest

from hardware.arduino import (
    ArduinoCommandError,
    ArduinoDisconnectedError,
    ArduinoOperationCancelledError,
)
from hardware.protocol import encode_message, parse_message
from hardware.serial_adapter import SerialArduino


class FakeSerialPort:
    def __init__(self, *, timeout=0.005, on_write=None):
        self.timeout = timeout
        self.on_write = on_write
        self.is_open = True
        self.writes = []
        self.incoming = Queue()

    def write(self, data):
        if not self.is_open:
            raise OSError("porta fechada")
        frame = data.decode("utf-8").strip()
        self.writes.append(frame)
        if self.on_write is not None:
            self.on_write(self, frame, len(self.writes))
        return len(data)

    def readline(self):
        if not self.is_open:
            return b""
        try:
            value = self.incoming.get(timeout=self.timeout)
        except Empty:
            return b""
        return f"{value}\n".encode("utf-8")

    def inject(self, frame):
        self.incoming.put(frame)

    def flush(self):
        return None

    def reset_input_buffer(self):
        while True:
            try:
                self.incoming.get_nowait()
            except Empty:
                return

    def close(self):
        self.is_open = False


class SerialArduinoTests(unittest.TestCase):
    def build_arduino(self, on_write):
        self.port = FakeSerialPort(on_write=on_write)
        self.arduino = SerialArduino(
            port="COM-TEST",
            baudrate=9600,
            read_timeout=0.005,
            boot_wait=0,
            serial_factory=lambda **_kwargs: self.port,
        )
        self.arduino.connect()
        return self.arduino

    def tearDown(self):
        if hasattr(self, "arduino"):
            self.arduino.disconnect()

    @staticmethod
    def acknowledge(port, frame, _attempt):
        command = parse_message(frame)
        port.inject(encode_message("ACK", command.cycle_id, command.payload))

    def test_sends_command_and_receives_correlated_ack(self):
        arduino = self.build_arduino(self.acknowledge)

        response = arduino.execute("garra:pegar", "cycle_1", timeout=0.1)

        self.assertEqual(response.kind, "ACK")
        self.assertEqual(response.payload, "GARRA:PEGAR")
        self.assertEqual(self.port.writes, ["CMD:cycle_1:GARRA:PEGAR"])

    def test_retries_after_command_timeout(self):
        def answer_second_attempt(port, frame, attempt):
            if attempt == 2:
                self.acknowledge(port, frame, attempt)

        arduino = self.build_arduino(answer_second_attempt)

        response = arduino.execute(
            "ESTEIRA:STOP",
            "cycle_2",
            timeout=0.03,
            retries=1,
        )

        self.assertEqual(response.kind, "ACK")
        self.assertEqual(len(self.port.writes), 2)

    def test_maps_error_frame_to_command_error(self):
        def reject(port, frame, _attempt):
            command = parse_message(frame)
            port.inject(
                encode_message(
                    "ERR",
                    command.cycle_id,
                    f"{command.payload}:MOTOR_BLOCKED",
                )
            )

        arduino = self.build_arduino(reject)

        with self.assertRaises(ArduinoCommandError) as context:
            arduino.execute("GARRA:HOME", "cycle_3", timeout=0.1)

        self.assertIn("MOTOR_BLOCKED", context.exception.message)

    def test_buffers_event_received_next_to_ack(self):
        def acknowledge_and_arrive(port, frame, _attempt):
            command = parse_message(frame)
            port.inject(encode_message("ACK", command.cycle_id, command.payload))
            port.inject(
                encode_message(
                    "EVT",
                    command.cycle_id,
                    "DESTINO_ALCANCADO:R04",
                )
            )

        arduino = self.build_arduino(acknowledge_and_arrive)
        arduino.execute("ESTEIRA:START", "cycle_4", timeout=0.1)

        event = arduino.wait_for_event(
            "DESTINO_ALCANCADO",
            "cycle_4",
            timeout=0.1,
        )

        self.assertEqual(event.payload, "DESTINO_ALCANCADO:R04")

    def test_ignores_malformed_lines_before_valid_ack(self):
        def noisy_ack(port, frame, attempt):
            port.inject("Arduino iniciou")
            self.acknowledge(port, frame, attempt)

        arduino = self.build_arduino(noisy_ack)

        response = arduino.execute("SISTEMA:RESET", "cycle_5", timeout=0.1)

        self.assertEqual(response.kind, "ACK")
        self.assertIn("Arduino iniciou", arduino.invalid_frames)

    def test_event_wait_can_be_cancelled(self):
        arduino = self.build_arduino(self.acknowledge)

        with self.assertRaises(ArduinoOperationCancelledError):
            arduino.wait_for_event(
                "DESTINO_ALCANCADO",
                "cycle_6",
                timeout=1,
                cancelled=lambda: True,
            )

    def test_stop_command_is_sent_while_an_event_is_pending(self):
        arduino = self.build_arduino(self.acknowledge)
        cancelled = Event()
        errors = []

        def wait_for_arrival():
            try:
                arduino.wait_for_event(
                    "DESTINO_ALCANCADO",
                    "cycle_7",
                    timeout=1,
                    cancelled=cancelled.is_set,
                )
            except Exception as exc:
                errors.append(exc)

        waiter = Thread(target=wait_for_arrival)
        waiter.start()
        response = arduino.execute("ESTEIRA:STOP", "cycle_7", timeout=0.1)
        cancelled.set()
        waiter.join(timeout=0.5)

        self.assertEqual(response.payload, "ESTEIRA:STOP")
        self.assertFalse(waiter.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ArduinoOperationCancelledError)

    def test_connection_error_is_exposed_as_domain_error(self):
        arduino = SerialArduino(
            port="COM-INEXISTENTE",
            boot_wait=0,
            serial_factory=lambda **_kwargs: (_ for _ in ()).throw(
                OSError("porta inexistente")
            ),
        )

        with self.assertRaises(ArduinoDisconnectedError) as context:
            arduino.connect()

        self.assertIn("COM-INEXISTENTE", context.exception.message)


if __name__ == "__main__":
    unittest.main()
