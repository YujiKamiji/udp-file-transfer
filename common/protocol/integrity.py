from zlib import crc32


def calculate_checksum(data: bytes, previous: int = 0) -> int:
    return crc32(data, previous)
