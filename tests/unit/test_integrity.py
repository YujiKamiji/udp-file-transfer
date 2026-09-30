import unittest

from common.protocol.integrity import calculate_checksum


class IntegrityTests(unittest.TestCase):
    def test_standard_crc32_vector(self) -> None:
        self.assertEqual(calculate_checksum(b"123456789"), 0xCBF43926)

    def test_empty_data(self) -> None:
        self.assertEqual(calculate_checksum(b""), 0)

    def test_checksum_can_be_calculated_in_blocks(self) -> None:
        checksum = calculate_checksum(b"1234")
        checksum = calculate_checksum(b"56789", checksum)
        self.assertEqual(checksum, 0xCBF43926)
