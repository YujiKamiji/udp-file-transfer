import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from client.application import main as client_main
from common.protocol.codec import decode_message, encode_message, encode_metadata
from common.protocol.messages import BLOCK_SIZE, Message, MessageType, Metadata
from server.application import main


class ApplicationLifecycleTests(unittest.TestCase):
    def test_client_cleans_up_when_interrupted_or_disconnected_during_download(self) -> None:
        for error, status in ((KeyboardInterrupt(), 130), (ConnectionResetError("connection lost"), 1)):
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as directory,
                patch("client.application.secrets.randbits", return_value=42),
                patch("client.application.UdpTransport") as transport_class,
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as stderr,
            ):
                server = ("127.0.0.1", 5000)
                transport = transport_class.return_value.__enter__.return_value
                transport.receive.side_effect = [
                    (encode_message(Message(MessageType.META, 42,
                        payload=encode_metadata(Metadata(BLOCK_SIZE * 2, 0)))), server),
                    (encode_message(Message(MessageType.DATA, 42, 1, b"x" * BLOCK_SIZE)), server),
                    error,
                ]
                self.assertEqual(client_main(["file.bin", "--output-dir", directory]), status)
                self.assertEqual(list(Path(directory).iterdir()), [])
                transport_class.return_value.__exit__.assert_called_once()
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_client_does_not_acknowledge_a_block_when_writing_fails(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("client.application.secrets.randbits", return_value=42),
            patch("client.application.UdpTransport") as transport_class,
            patch("client.file_writer.FileWriter.write_block", side_effect=OSError("disk full")),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            server = ("127.0.0.1", 5000)
            transport = transport_class.return_value.__enter__.return_value
            transport.receive.side_effect = [
                (encode_message(Message(MessageType.META, 42,
                    payload=encode_metadata(Metadata(4, 0)))), server),
                (encode_message(Message(MessageType.DATA, 42, 1, b"data")), server),
            ]
            self.assertEqual(client_main(["file.bin", "--output-dir", directory]), 1)
            sent = [decode_message(call.args[0]) for call in transport.send_to.call_args_list]
            self.assertEqual([(message.message_type, message.sequence) for message in sent],
                             [(MessageType.GET, 0), (MessageType.ACK, 0)])
            self.assertEqual(list(Path(directory).iterdir()), [])
            transport_class.return_value.__exit__.assert_called_once()
            self.assertIn("disk full", stderr.getvalue())

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
