from dataclasses import dataclass
from enum import IntEnum


BLOCK_SIZE = 1024
MAX_SEQUENCE = 2**32 - 1
MAX_FILE_SIZE = (MAX_SEQUENCE - 1) * BLOCK_SIZE


class MessageType(IntEnum):
    GET = 1
    META = 2
    DATA = 3
    ACK = 4
    NACK = 5
    FIN = 6
    ERROR = 7





class ErrorCode(IntEnum):
    NOT_FOUND = 1
    FORBIDDEN = 2
    BAD_REQUEST = 3
    IO_ERROR = 4


@dataclass(frozen=True)
class Message:
    message_type: MessageType
    transfer_id: int
    sequence: int = 0
    payload: bytes = b""




@dataclass(frozen=True)
class Metadata:
    file_size: int
    checksum: int

    @property
    def block_count(self) -> int:
        return (self.file_size + BLOCK_SIZE - 1) // BLOCK_SIZE
