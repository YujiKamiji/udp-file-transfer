import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from common.protocol.codec import encode_message
from common.protocol.messages import Message, MessageType
from server.application import main


class ApplicationLifecycleTests(unittest.TestCase):
    def test_server_keeps_receiving_after_timeout_and_closes_on_interrupt(self) -> None:
        request = encode_message(Message(MessageType.GET, 42, payload=b"file.bin"))
        output = io.StringIO()
        with (
            patch("server.application.UdpTransport") as transport_class,
            patch("server.application.FileRepository") as repository_class,
        ):
            repository_class.return_value.open.side_effect = FileNotFoundError("missing")
            transport = transport_class.return_value.__enter__.return_value
            transport.receive.side_effect = [
                TimeoutError(),
                (request, ("127.0.0.1", 6000)),
                KeyboardInterrupt(),
            ]
            with redirect_stdout(output):
                self.assertEqual(main([]), 0)
            transport_class.return_value.__exit__.assert_called_once()
        self.assertIn("file.bin", output.getvalue())
        self.assertIn("servidor encerrado", output.getvalue())
