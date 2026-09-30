import struct
import unittest
import zlib

from common.protocol.codec import (
    ChecksumError,
    ProtocolError,
    decode_message,
    decode_metadata,
    encode_message,
    encode_metadata,
)
from common.protocol.messages import (
    MAX_FILE_SIZE,
    MAX_SEQUENCE,
    ErrorCode,
    Message,
    MessageType,
    Metadata,
)


def make_packet(kind: int, transfer_id: int, sequence: int, payload: bytes) -> bytes:
    prefix = struct.pack("!BII", kind, transfer_id, sequence)
    return prefix + struct.pack("!I", zlib.crc32(prefix + payload)) + payload


class ProtocolTests(unittest.TestCase):
    def test_round_trip_for_every_message_type(self) -> None:
        messages = [
            Message(MessageType.GET, 42, payload="relatório.bin".encode("utf-8")),
            Message(MessageType.META, 42, payload=encode_metadata(Metadata(1025, 123))),
            Message(MessageType.DATA, 42, 1, b"\x00\xff\x80"),
            Message(MessageType.ACK, 42, 0),
            Message(MessageType.ACK, 42, 1),
            Message(MessageType.NACK, 42, 1),
            Message(MessageType.FIN, 42, 2),
            Message(MessageType.ERROR, 42, payload=bytes([ErrorCode.NOT_FOUND])),
        ]
        for message in messages:
            with self.subTest(kind=message.message_type, sequence=message.sequence):
                self.assertEqual(decode_message(encode_message(message)), message)

    def test_header_uses_network_byte_order_and_crc_covers_header_and_payload(self) -> None:
        payload = b"abc"
        packet = encode_message(Message(MessageType.DATA, 0x01020304, 0x05060708, payload))
        prefix = bytes.fromhex("03 01 02 03 04 05 06 07 08")
        self.assertEqual(packet[:9], prefix)
        self.assertEqual(packet[9:13], zlib.crc32(prefix + payload).to_bytes(4, "big"))
        self.assertEqual(packet[13:], payload)
        self.assertEqual(len(packet), 16)

    def test_maximum_data_block_and_short_final_block(self) -> None:
        for payload in (b"x", bytes(range(256)) * 4):
            with self.subTest(size=len(payload)):
                message = Message(MessageType.DATA, MAX_SEQUENCE, 1, payload)
                packet = encode_message(message)
                self.assertEqual(len(packet), 13 + len(payload))
                self.assertLessEqual(len(packet), 1037)
                self.assertEqual(decode_message(packet), message)

    def test_rejects_single_bit_corruption_anywhere_in_packet(self) -> None:
        packet = encode_message(Message(MessageType.DATA, 42, 1, b"file contents"))
        for index in range(len(packet)):
            for bit in range(8):
                with self.subTest(index=index, bit=bit):
                    corrupted = bytearray(packet)
                    corrupted[index] ^= 1 << bit
                    with self.assertRaises(ChecksumError):
                        decode_message(bytes(corrupted))

    def test_rejects_truncated_and_extended_packets(self) -> None:
        packet = encode_message(Message(MessageType.DATA, 42, 1, b"file contents"))
        for size in range(len(packet)):
            with self.subTest(size=size):
                with self.assertRaises(ProtocolError):
                    decode_message(packet[:size])
        with self.assertRaises(ChecksumError):
            decode_message(packet + b"extra")

    def test_rejects_invalid_messages_even_with_a_valid_checksum(self) -> None:
        cases = [
            (99, 0, b""),
            (1, 1, b"file.bin"),
            (1, 0, b""),
            (1, 0, b"\xff"),
            (1, 0, b"file\x00.bin"),
            (1, 0, b"x" * 1025),
            (2, 1, struct.pack("!QI", 0, 0)),
            (2, 0, b""),
            (2, 0, struct.pack("!QI", MAX_FILE_SIZE + 1, 0)),
            (3, 0, b"data"),
            (3, MAX_SEQUENCE, b"data"),
            (3, 1, b""),
            (3, 1, b"x" * 1025),
            (4, 0, b"unexpected"),
            (5, 0, b""),
            (5, MAX_SEQUENCE, b""),
            (5, 1, b"unexpected"),
            (6, 0, b""),
            (6, 1, b"unexpected"),
            (7, 1, b"\x01"),
            (7, 0, b""),
            (7, 0, b"\xff"),
            (7, 0, b"\x01\x02"),
        ]
        for kind, sequence, payload in cases:
            with self.subTest(kind=kind, sequence=sequence, payload=payload[:16]):
                with self.assertRaises(ProtocolError):
                    decode_message(make_packet(kind, 42, sequence, payload))
                if kind in [member.value for member in MessageType]:
                    with self.assertRaises(ProtocolError):
                        encode_message(Message(MessageType(kind), 42, sequence, payload))

    def test_rejects_out_of_range_or_noninteger_header_fields(self) -> None:
        for value in (-1, 2**32, 1.5, True, "1"):
            for field in ("transfer_id", "sequence"):
                with self.subTest(field=field, value=value):
                    arguments = {"transfer_id": 1, "sequence": 0}
                    arguments[field] = value
                    with self.assertRaises(ProtocolError):
                        encode_message(Message(MessageType.ACK, **arguments))

    def test_rejects_wrong_input_types(self) -> None:
        with self.assertRaises(ProtocolError):
            encode_message(Message(99, 1))
        with self.assertRaises(ProtocolError):
            encode_message(Message(MessageType.DATA, 1, 1, "text"))
        with self.assertRaises(ProtocolError):
            decode_message("text")

    def test_accepts_all_defined_error_codes(self) -> None:
        for code in ErrorCode:
            with self.subTest(code=code):
                message = Message(MessageType.ERROR, 42, payload=bytes([code]))
                self.assertEqual(decode_message(encode_message(message)), message)

    def test_keeps_path_validation_separate_from_message_format(self) -> None:
        message = Message(MessageType.GET, 42, payload=b"../file.bin")
        self.assertEqual(decode_message(encode_message(message)), message)


class MetadataTests(unittest.TestCase):
    def test_metadata_binary_layout(self) -> None:
        metadata = Metadata(1025, 0xCBF43926)
        expected = bytes.fromhex("00 00 00 00 00 00 04 01 cb f4 39 26")
        self.assertEqual(encode_metadata(metadata), expected)
        self.assertEqual(decode_metadata(expected), metadata)

    def test_block_count_and_fin_sequence_fit_header(self) -> None:
        cases = (
            (0, 0),
            (1, 1),
            (1024, 1),
            (1025, 2),
            (MAX_FILE_SIZE, MAX_SEQUENCE - 1),
        )
        for size, blocks in cases:
            with self.subTest(size=size):
                metadata = decode_metadata(encode_metadata(Metadata(size, 0)))
                self.assertEqual(metadata.block_count, blocks)
                message = Message(MessageType.FIN, 42, metadata.block_count + 1)
                self.assertEqual(decode_message(encode_message(message)), message)

    def test_rejects_invalid_metadata_fields(self) -> None:
        cases = [
            Metadata(-1, 0),
            Metadata(MAX_FILE_SIZE + 1, 0),
            Metadata(0, -1),
            Metadata(0, 2**32),
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                with self.assertRaises(ProtocolError):
                    encode_metadata(metadata)

    def test_rejects_metadata_with_wrong_length(self) -> None:
        for size in (0, 11, 13):
            with self.subTest(size=size):
                with self.assertRaises(ProtocolError):
                    decode_metadata(b"\x00" * size)
