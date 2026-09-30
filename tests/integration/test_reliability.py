import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from client.transfer import receive_file
from common.config import MAX_ATTEMPTS
from common.protocol.codec import decode_message, encode_message
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport
from server.file_repository import FileRepository
from server.transfer import send_file


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.shared_dir = self.directory / "shared"
        self.shared_dir.mkdir()
        self.output_dir = self.directory / "downloads"
        self.data = bytes(range(256)) * 9
        (self.shared_dir / "file.bin").write_bytes(self.data)
        self.server = self.enterContext(UdpTransport(("127.0.0.1", 0), timeout=0.05))
        self.client = self.enterContext(UdpTransport(("127.0.0.1", 0), timeout=0.05))
        self.server_errors = []
        self.sent = Counter()

    def serve(self) -> None:
        try:
            packet, sender = self.server.receive(timeout=2)
            request = decode_message(packet)
            with FileRepository(self.shared_dir).open("file.bin") as shared:
                send_file(self.server, shared, request.transfer_id, sender, 0.05)
        except Exception as error:
            self.server_errors.append(error)

    def start_server(self) -> threading.Thread:
        worker = threading.Thread(target=self.serve, daemon=True)
        self.addCleanup(worker.join, 3)
        worker.start()
        return worker

    def test_recovers_control_data_and_ack_losses_corruption_and_duplicates(self) -> None:
        final_sequence = 4
        drop_once = {
            (MessageType.GET, 0), (MessageType.META, 0), (MessageType.ACK, 0),
            (MessageType.ACK, 1), (MessageType.DATA, 2),
            (MessageType.FIN, final_sequence), (MessageType.ACK, final_sequence),
        }
        corrupt_once = {(MessageType.DATA, 3)}
        duplicate_once = {(MessageType.DATA, 2)}

        def faulty_sender(original):
            def send(packet, destination):
                message = decode_message(packet)
                key = (message.message_type, message.sequence)
                self.sent[key] += 1
                if key in drop_once:
                    drop_once.remove(key)
                    return
                if key in corrupt_once:
                    corrupt_once.remove(key)
                    damaged = bytearray(packet)
                    damaged[-1] ^= 1
                    original(bytes(damaged), destination)
                    return
                original(packet, destination)
                if key in duplicate_once:
                    duplicate_once.remove(key)
                    original(packet, destination)
            return send

        with (
            patch.object(self.server, "send_to", side_effect=faulty_sender(self.server.send_to)),
            patch.object(self.client, "send_to", side_effect=faulty_sender(self.client.send_to)),
        ):
            worker = self.start_server()
            request = Message(MessageType.GET, 42, payload=b"file.bin")
            destination = receive_file(self.client, self.server.local_address, request, self.output_dir, 0.05)
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.server_errors, [])
        self.assertEqual(destination.read_bytes(), self.data)
        self.assertFalse(destination.with_name("file.bin.part").exists())
        self.assertFalse(drop_once | corrupt_once | duplicate_once)
        self.assertGreaterEqual(self.sent[(MessageType.NACK, 3)], 1)
        for key in ((MessageType.GET, 0), (MessageType.DATA, 1), (MessageType.DATA, 2), (MessageType.FIN, 4)):
            with self.subTest(key=key):
                self.assertGreaterEqual(self.sent[key], 2)

    def test_permanent_data_loss_stops_at_limit_and_removes_partial(self) -> None:
        original = self.server.send_to

        def drop_data(packet, destination):
            message = decode_message(packet)
            key = (message.message_type, message.sequence)
            self.sent[key] += 1
            if message.message_type != MessageType.DATA:
                original(packet, destination)

        with patch.object(self.server, "send_to", side_effect=drop_data):
            worker = self.start_server()
            request = Message(MessageType.GET, 42, payload=b"file.bin")
            with self.assertRaises(TimeoutError):
                receive_file(self.client, self.server.local_address, request, self.output_dir, 0.05)
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.server_errors), 1)
        self.assertIsInstance(self.server_errors[0], TimeoutError)
        self.assertEqual(self.sent[(MessageType.DATA, 1)], MAX_ATTEMPTS)
        self.assertEqual(list(self.output_dir.iterdir()), [])
