import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from common.protocol.codec import decode_message, encode_message
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport
from server.dispatcher import TransferDispatcher
from server.file_repository import FileRepository


class ShutdownTests(unittest.TestCase):
    def test_server_closes_active_transfers_without_waiting_for_ack_timeouts(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            UdpTransport(("127.0.0.1", 0), 2) as server,
            UdpTransport(("127.0.0.1", 0), 2) as first,
            UdpTransport(("127.0.0.1", 0), 2) as second,
            redirect_stdout(io.StringIO()) as output,
        ):
            root = Path(directory)
            (root / "file.bin").write_bytes(b"contents")
            repository = FileRepository(root)
            dispatcher = TransferDispatcher(server, repository, 10)
            opened = []
            open_file = repository.open

            def track_open(filename):
                shared = open_file(filename)
                opened.append(shared)
                return shared

            try:
                with patch.object(repository, "open", side_effect=track_open):
                    for transfer_id, client in enumerate((first, second), start=1):
                        client.send_to(encode_message(Message(
                            MessageType.GET, transfer_id, payload=b"file.bin")), server.local_address)
                        dispatcher.dispatch(*server.receive())
                        metadata, _ = client.receive()
                        self.assertEqual(decode_message(metadata).message_type, MessageType.META)
                        client.send_to(encode_message(Message(MessageType.ACK, transfer_id)), server.local_address)
                        dispatcher.dispatch(*server.receive())
                        data, _ = client.receive()
                        self.assertEqual(decode_message(data).message_type, MessageType.DATA)
                workers = [worker for _, worker in dispatcher._active.values()]
                started = time.monotonic()
                dispatcher.close()
                self.assertLess(time.monotonic() - started, 2)
                self.assertEqual(len(opened), 2)
                self.assertTrue(all(shared._file.closed for shared in opened))
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                self.assertEqual(dispatcher._active, {})
                self.assertEqual(output.getvalue().count("servidor encerrado."), 2)
            finally:
                dispatcher.close()
