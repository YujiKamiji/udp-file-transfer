import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client.file_writer import FileWriter
from common.protocol.integrity import calculate_checksum
from common.protocol.messages import BLOCK_SIZE, Metadata


class FileWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.destination = Path(self.directory) / "downloads" / "file.bin"

    def metadata_for(self, data: bytes) -> Metadata:
        return Metadata(len(data), calculate_checksum(data))

    def test_reconstructs_binary_file_and_only_publishes_after_validation(self) -> None:
        data = bytes(range(256)) * 5
        with FileWriter(self.destination, self.metadata_for(data)) as writer:
            self.assertEqual(writer.partial_path, self.destination.with_name("file.bin.part"))
            self.assertTrue(writer.partial_path.is_file())
            writer.write_block(1, data[:BLOCK_SIZE])
            writer.write_block(2, data[BLOCK_SIZE:])
            self.assertFalse(self.destination.exists())
            self.assertEqual(writer.finalize(), self.destination)
            self.assertEqual(self.destination.read_bytes(), data)
            self.assertFalse(writer.partial_path.exists())
            self.assertEqual(writer.finalize(), self.destination)
        self.assertEqual(self.destination.read_bytes(), data)

    def test_finalizes_an_empty_file(self) -> None:
        with FileWriter(self.destination, self.metadata_for(b"")) as writer:
            writer.finalize()
        self.assertEqual(self.destination.read_bytes(), b"")

    def test_incomplete_file_can_receive_remaining_blocks_after_failed_finalization(self) -> None:
        data = b"a" * (BLOCK_SIZE + 1)
        with FileWriter(self.destination, self.metadata_for(data)) as writer:
            writer.write_block(1, data[:BLOCK_SIZE])
            with self.assertRaises(ValueError):
                writer.finalize()
            self.assertFalse(self.destination.exists())
            writer.write_block(2, data[BLOCK_SIZE:])
            writer.finalize()
        self.assertEqual(self.destination.read_bytes(), data)

    def test_rejects_bad_checksum_and_removes_partial_on_exit(self) -> None:
        with FileWriter(self.destination, self.metadata_for(b"good")) as writer:
            writer.write_block(1, b"evil")
            with self.assertRaises(ValueError):
                writer.finalize()
            self.assertFalse(self.destination.exists())
        self.assertFalse(writer.partial_path.exists())

    def test_rejects_unexpected_duplicate_and_wrong_size_blocks(self) -> None:
        data = b"x" * (BLOCK_SIZE + 1)
        with FileWriter(self.destination, self.metadata_for(data)) as writer:
            for sequence, payload in ((2, b"x"), (0, b"x"), (True, data[:BLOCK_SIZE]), (1, b"x")):
                with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                    writer.write_block(sequence, payload)
            writer.write_block(1, data[:BLOCK_SIZE])
            with self.assertRaises(ValueError):
                writer.write_block(1, data[:BLOCK_SIZE])
            writer.write_block(2, data[BLOCK_SIZE:])
            with self.assertRaises(ValueError):
                writer.write_block(3, b"x")
            writer.finalize()
        self.assertEqual(self.destination.read_bytes(), data)

    def test_preserves_an_existing_destination(self) -> None:
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            FileWriter(self.destination, self.metadata_for(b"new"))
        self.assertEqual(self.destination.read_bytes(), b"original")
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_rejects_a_second_writer_for_the_same_destination(self) -> None:
        with FileWriter(self.destination, self.metadata_for(b"first")) as first:
            first.write_block(1, b"first")
            with self.assertRaises(FileExistsError):
                FileWriter(self.destination, self.metadata_for(b"second"))
            first.finalize()
        self.assertEqual(self.destination.read_bytes(), b"first")
        self.assertFalse(first.partial_path.exists())

    def test_preserves_an_existing_partial(self) -> None:
        self.destination.parent.mkdir()
        partial = self.destination.with_name("file.bin.part")
        partial.write_bytes(b"previous download")
        with self.assertRaises(FileExistsError):
            FileWriter(self.destination, self.metadata_for(b"new"))
        self.assertEqual(partial.read_bytes(), b"previous download")

    def test_preserves_a_destination_created_during_download(self) -> None:
        with FileWriter(self.destination, self.metadata_for(b"new")) as writer:
            writer.write_block(1, b"new")
            self.destination.write_bytes(b"existing file")
            with self.assertRaises(FileExistsError):
                writer.finalize()
        self.assertEqual(self.destination.read_bytes(), b"existing file")
        self.assertFalse(writer.partial_path.exists())

    def test_removes_partial_when_transfer_is_interrupted(self) -> None:
        with self.assertRaises(RuntimeError):
            with FileWriter(self.destination, self.metadata_for(b"contents")) as writer:
                writer.write_block(1, b"contents")
                raise RuntimeError("interrupted")
        self.assertFalse(writer.partial_path.exists())
        self.assertFalse(self.destination.exists())

    def test_cleanup_after_failure_to_publish(self) -> None:
        with FileWriter(self.destination, self.metadata_for(b"data")) as writer:
            writer.write_block(1, b"data")
            with patch("client.file_writer.Path.rename", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    writer.finalize()
        self.assertFalse(writer.partial_path.exists())
        self.assertFalse(self.destination.exists())

    def test_closed_writer_rejects_further_operations(self) -> None:
        writer = FileWriter(self.destination, self.metadata_for(b"data"))
        writer.close()
        writer.close()
        with self.assertRaises(ValueError):
            writer.write_block(1, b"data")
        with self.assertRaises(ValueError):
            writer.finalize()

    def test_closing_an_old_writer_does_not_remove_a_new_partial(self) -> None:
        previous = FileWriter(self.destination, self.metadata_for(b"data"))
        previous.close()
        with FileWriter(self.destination, self.metadata_for(b"data")) as current:
            previous.close()
            self.assertTrue(current.partial_path.exists())
            current.write_block(1, b"data")
            current.finalize()
        self.assertEqual(self.destination.read_bytes(), b"data")

    def test_invalid_metadata_does_not_create_files(self) -> None:
        with self.assertRaises(ValueError):
            FileWriter(self.destination, Metadata(-1, 0))
        self.assertFalse(self.destination.parent.exists())
