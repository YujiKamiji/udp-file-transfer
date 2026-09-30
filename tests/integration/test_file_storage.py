import tempfile
import unittest
from pathlib import Path

from client.file_writer import FileWriter
from server.file_repository import FileRepository


class FileStorageTests(unittest.TestCase):
    def test_reconstructs_file_larger_than_ten_megabytes_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared_folder = root / "shared"
            shared_folder.mkdir()
            source = shared_folder / "large.bin"
            chunk = bytes(range(256)) * 256
            with source.open("wb") as output:
                for _ in range(161):
                    output.write(chunk)
            destination = root / "downloads" / "large.bin"
            repository = FileRepository(shared_folder)
            with repository.open("large.bin") as shared:
                self.assertGreater(shared.metadata.file_size, 10 * 1024 * 1024)
                with FileWriter(destination, shared.metadata) as writer:
                    for sequence in range(1, shared.metadata.block_count + 1):
                        writer.write_block(sequence, shared.read_block(sequence))
                    writer.finalize()
            with source.open("rb") as original, destination.open("rb") as received:
                while data := original.read(65536):
                    self.assertEqual(received.read(len(data)), data)
                self.assertEqual(received.read(1), b"")
