

#tipo (1 byte) | identificador (4 bytes) | sequência (4 bytes) | crc32 (4 bytes) | conteúdo


import struct

from common.protocol.integrity import calculate_checksum
from common.protocol.messages import (
    BLOCK_SIZE,
    MAX_FILE_SIZE,
    MAX_SEQUENCE,
    ErrorCode,
    Message,
    MessageType,
    Metadata,
)


_PREFIX = struct.Struct("!BII")
_CHECKSUM = struct.Struct("!I")
_METADATA = struct.Struct("!QI")
HEADER_SIZE = _PREFIX.size + _CHECKSUM.size
MAX_PACKET_SIZE = HEADER_SIZE + BLOCK_SIZE


class ProtocolError(ValueError):
    pass


class ChecksumError(ProtocolError):
    pass


def _validate_integer(value: int, maximum: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ProtocolError(f"Invalid {name}: expected an integer from 0 to {maximum}")


def encode_metadata(metadata: Metadata) -> bytes:
    _validate_integer(metadata.file_size, MAX_FILE_SIZE, "file size")
    _validate_integer(metadata.checksum, MAX_SEQUENCE, "file checksum")
    return _METADATA.pack(metadata.file_size, metadata.checksum)


def decode_metadata(payload: bytes) -> Metadata:
    if len(payload) != _METADATA.size:
        raise ProtocolError("Metadata must contain exactly 12 bytes")
    file_size, checksum = _METADATA.unpack(payload)
    _validate_integer(file_size, MAX_FILE_SIZE, "file size")
    return Metadata(file_size, checksum)


def _validate_message(message: Message) -> None:
    if not isinstance(message.message_type, MessageType):
        raise ProtocolError("Unknown message type")
    _validate_integer(message.transfer_id, MAX_SEQUENCE, "transfer ID")
    _validate_integer(message.sequence, MAX_SEQUENCE, "sequence")
    if not isinstance(message.payload, bytes):
        raise ProtocolError("Payload must be bytes")
    if len(message.payload) > BLOCK_SIZE:
        raise ProtocolError("Payload exceeds 1024 bytes")

    kind = message.message_type
    if kind in (MessageType.GET, MessageType.META, MessageType.ERROR):
        if message.sequence != 0:
            raise ProtocolError("GET, META and ERROR must use sequence 0")
    elif kind in (MessageType.DATA, MessageType.NACK):
        if not 1 <= message.sequence < MAX_SEQUENCE:
            raise ProtocolError("Invalid block sequence")
    elif kind == MessageType.FIN and message.sequence == 0:
        raise ProtocolError("FIN must use a positive sequence")

    if kind == MessageType.GET:
        try:
            filename = message.payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError("Filename must be valid UTF-8") from error
        if not filename or "\x00" in filename:
            raise ProtocolError("Filename must be nonempty and contain no null bytes")
    elif kind == MessageType.META:
        decode_metadata(message.payload)
    elif kind == MessageType.DATA:
        if not message.payload:
            raise ProtocolError("DATA must contain file bytes")
    elif kind == MessageType.ERROR:
        if len(message.payload) != 1:
            raise ProtocolError("ERROR must contain one error code byte")
        try:
            ErrorCode(message.payload[0])
        except ValueError as error:
            raise ProtocolError("Unknown error code") from error
    elif message.payload:
        raise ProtocolError("ACK, NACK and FIN must have empty payloads")


def encode_message(message: Message) -> bytes:
    _validate_message(message)
    prefix = _PREFIX.pack(
        message.message_type, message.transfer_id, message.sequence
    )
    checksum = calculate_checksum(prefix + message.payload)
    return prefix + _CHECKSUM.pack(checksum) + message.payload


def decode_message(packet: bytes) -> Message:
    if not isinstance(packet, bytes):
        raise ProtocolError("Packet must be bytes")
    if not HEADER_SIZE <= len(packet) <= MAX_PACKET_SIZE:
        raise ProtocolError("Invalid packet size")

    prefix = packet[:_PREFIX.size]
    payload = packet[HEADER_SIZE:]
    checksum = _CHECKSUM.unpack_from(packet, _PREFIX.size)[0]
    if calculate_checksum(prefix + payload) != checksum:
        raise ChecksumError("Packet checksum mismatch")

    kind, transfer_id, sequence = _PREFIX.unpack(prefix)
    try:
        message_type = MessageType(kind)
    except ValueError as error:
        raise ProtocolError("Unknown message type") from error
    message = Message(message_type, transfer_id, sequence, payload)
    _validate_message(message)
    return message
