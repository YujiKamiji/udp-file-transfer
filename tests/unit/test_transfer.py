import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from client.transfer import receive_file, request_metadata
from common.config import MAX_ATTEMPTS
from common.protocol.codec import decode_message, encode_message, encode_metadata
from common.protocol.integrity import calculate_checksum
from common.protocol.messages import Message, MessageType, Metadata
from server.transfer import send_and_wait_for_ack


class TransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.server = ("127.0.0.1", 5000)
        self.request = Message(MessageType.GET, 42, payload=b"file.bin")

    def packet(self, kind: MessageType, sequence: int = 0, payload: bytes = b"") -> tuple:
        return encode_message(Message(kind, 42, sequence, payload)), self.server

    def test_client_saves_data_and_acknowledges_metadata_blocks_and_finish(self) -> None:
        data = b"contents"
        metadata = encode_metadata(Metadata(len(data), calculate_checksum(data)))
        transport = Mock()
        transport.receive.side_effect = [
            (b"invalid", self.server),
            self.packet(MessageType.META, payload=metadata),
            self.packet(MessageType.DATA, 1, data),
            self.packet(MessageType.FIN, 2),
            TimeoutError(),
        ]
        destination = receive_file(transport, self.server, self.request, self.output_dir, 1)
        self.assertEqual(destination.read_bytes(), data)
        sent = [decode_message(call.args[0]) for call in transport.send_to.call_args_list]
        self.assertEqual(
            [(message.message_type, message.sequence) for message in sent],
            [(MessageType.GET, 0), (MessageType.ACK, 0), (MessageType.ACK, 1), (MessageType.ACK, 2)],
        )

    def test_timeout_during_download_removes_partial(self) -> None:
        transport = Mock()
        transport.receive.side_effect = [
            self.packet(MessageType.META, payload=encode_metadata(Metadata(2048, 0))),
            self.packet(MessageType.DATA, 1, b"x" * 1024),
            TimeoutError(),
        ]
        with self.assertRaises(TimeoutError):
            receive_file(transport, self.server, self.request, self.output_dir, 1)
        self.assertEqual(list(self.output_dir.iterdir()), [])

    def test_bad_file_checksum_does_not_acknowledge_finish_or_keep_file(self) -> None:
        metadata = encode_metadata(Metadata(4, calculate_checksum(b"good")))
        transport = Mock()
        transport.receive.side_effect = [
            self.packet(MessageType.META, payload=metadata),
            self.packet(MessageType.DATA, 1, b"evil"),
            self.packet(MessageType.FIN, 2),
        ]
        with self.assertRaises(ValueError):
            receive_file(transport, self.server, self.request, self.output_dir, 1)
        sent = [decode_message(call.args[0]) for call in transport.send_to.call_args_list]
        self.assertEqual([message.sequence for message in sent], [0, 0, 1])
        self.assertEqual(list(self.output_dir.iterdir()), [])

    def test_ack_must_match_peer_transfer_and_sequence(self) -> None:
        transport = Mock()
        message = Message(MessageType.DATA, 42, 1, b"contents")
        transport.receive.side_effect = [
            (encode_message(Message(MessageType.ACK, 42, 1)), ("127.0.0.1", 5001)),
            (encode_message(Message(MessageType.ACK, 43, 1)), self.server),
            self.packet(MessageType.ACK, 0),
            self.packet(MessageType.ACK, 1),
        ]
        send_and_wait_for_ack(transport, message, self.server, 1)
        transport.send_to.assert_called_once_with(encode_message(message), self.server)
        self.assertEqual(transport.receive.call_count, 4)

    def test_server_stops_after_the_attempt_limit(self) -> None:
        transport = Mock()
        transport.receive.side_effect = TimeoutError()
        with self.assertRaisesRegex(TimeoutError, "ack 1"):
            send_and_wait_for_ack(transport, Message(MessageType.DATA, 42, 1, b"x"), self.server, 1)
        self.assertEqual(transport.send_to.call_count, MAX_ATTEMPTS)

    def test_retransmits_the_same_packet_after_timeout(self) -> None:
        transport = Mock()
        transport.receive.side_effect = [TimeoutError(), self.packet(MessageType.ACK, 1)]
        message = Message(MessageType.DATA, 42, 1, b"contents")
        send_and_wait_for_ack(transport, message, self.server, 1)
        self.assertEqual(transport.send_to.call_count, 2)
        self.assertEqual(transport.send_to.call_args_list[0], transport.send_to.call_args_list[1])

    def test_retransmits_requested_block_on_nack(self) -> None:
        transport = Mock()
        transport.receive.side_effect = [
            self.packet(MessageType.NACK, 2),
            self.packet(MessageType.NACK, 1),
            self.packet(MessageType.ACK, 1),
        ]
        send_and_wait_for_ack(transport, Message(MessageType.DATA, 42, 1, b"x"), self.server, 1)
        self.assertEqual(transport.send_to.call_count, 2)

    def test_repeated_get_resends_metadata(self) -> None:
        transport = Mock()
        transport.receive.side_effect = [
            (encode_message(self.request), self.server),
            self.packet(MessageType.ACK, 0),
        ]
        message = Message(MessageType.META, 42, payload=encode_metadata(Metadata(0, 0)))
        send_and_wait_for_ack(transport, message, self.server, 1)
        self.assertEqual(transport.send_to.call_count, 2)

    def test_get_retries_keep_the_same_transfer_id(self) -> None:
        transport = Mock()
        transport.receive.side_effect = [
            TimeoutError(), self.packet(MessageType.META, payload=encode_metadata(Metadata(0, 0))),
        ]
        request_metadata(transport, self.server, self.request, 1)
        self.assertEqual(transport.send_to.call_count, 2)
        self.assertEqual(transport.send_to.call_args_list[0], transport.send_to.call_args_list[1])

    def test_get_stops_after_attempt_limit(self) -> None:
        transport = Mock()
        transport.receive.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            receive_file(transport, self.server, self.request, self.output_dir, 1)
        self.assertEqual(transport.send_to.call_count, MAX_ATTEMPTS)
        self.assertEqual(list(self.output_dir.iterdir()), [])

    def test_duplicates_are_acknowledged_without_writing_data_twice(self) -> None:
        data = b"contents"
        metadata = self.packet(
            MessageType.META, payload=encode_metadata(Metadata(len(data), calculate_checksum(data)))
        )
        block = self.packet(MessageType.DATA, 1, data)
        finish = self.packet(MessageType.FIN, 2)
        transport = Mock()
        transport.receive.side_effect = [metadata, metadata, block, block, finish, finish, TimeoutError()]
        destination = receive_file(transport, self.server, self.request, self.output_dir, 1)
        self.assertEqual(destination.read_bytes(), data)
        sent = [decode_message(call.args[0]) for call in transport.send_to.call_args_list]
        self.assertEqual([message.sequence for message in sent], [0, 0, 0, 1, 1, 2, 2])

    def test_corrupted_packet_requests_expected_block_without_trusting_header(self) -> None:
        data = b"contents"
        damaged = bytearray(encode_message(Message(MessageType.DATA, 42, 1, data)))
        damaged[8] ^= 1
        transport = Mock()
        transport.receive.side_effect = [
            self.packet(MessageType.META, payload=encode_metadata(Metadata(len(data), calculate_checksum(data)))),
            (bytes(damaged), self.server),
            self.packet(MessageType.DATA, 1, data),
            self.packet(MessageType.FIN, 2),
            TimeoutError(),
        ]
        destination = receive_file(transport, self.server, self.request, self.output_dir, 1)
        self.assertEqual(destination.read_bytes(), data)
        sent = [decode_message(call.args[0]) for call in transport.send_to.call_args_list]
        nacks = [message.sequence for message in sent if message.message_type == MessageType.NACK]
        self.assertEqual(nacks, [1])
