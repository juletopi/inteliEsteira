import unittest

from hardware.protocol import (
    ProtocolError,
    encode_message,
    parse_message,
    validate_command,
)


class ProtocolTests(unittest.TestCase):
    def test_round_trip_preserves_command_payload(self):
        frame = encode_message("cmd", "cycle_1", "destino:r08")
        message = parse_message(frame)

        self.assertEqual(frame, "CMD:cycle_1:DESTINO:R08")
        self.assertEqual(message.kind, "CMD")
        self.assertEqual(message.cycle_id, "cycle_1")
        self.assertEqual(message.payload, "DESTINO:R08")

    def test_accepts_only_known_destinations(self):
        self.assertEqual(validate_command("destino:r10"), "DESTINO:R10")
        with self.assertRaises(ProtocolError):
            validate_command("DESTINO:R11")

    def test_rejects_malformed_frame(self):
        with self.assertRaises(ProtocolError):
            parse_message("ESTEIRA:START")


if __name__ == "__main__":
    unittest.main()
