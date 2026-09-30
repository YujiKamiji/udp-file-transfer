import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.protocol.integrity import calculate_checksum
from common.protocol.messages import BLOCK_SIZE
from server.file_repository import FileRepository


class FileRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory) / "shared"
        self.root.mkdir()
        self.repository = FileRepository(self.root)

    def test_reads_binary_file_metadata_and_specific_blocks(self) -> None:
        data = bytes(range(256)) * 5
        (self.root / "file.bin").write_bytes(data)
        with self.repository.open("file.bin") as shared:
            self.assertEqual(shared.metadata.file_size, len(data))
            self.assertEqual(shared.metadata.checksum, calculate_checksum(data))
            self.assertEqual(shared.metadata.block_count, 2)
            self.assertEqual(shared.read_block(2), data[BLOCK_SIZE:])
            self.assertEqual(shared.read_block(1), data[:BLOCK_SIZE])
            self.assertEqual(shared.read_block(1), data[:BLOCK_SIZE])

    def test_empty_file_has_no_blocks(self) -> None:
        (self.root / "empty.bin").write_bytes(b"")
        with self.repository.open("empty.bin") as shared:
            self.assertEqual(shared.metadata.file_size, 0)
            self.assertEqual(shared.metadata.checksum, 0)
            self.assertEqual(shared.metadata.block_count, 0)
            with self.assertRaises(ValueError):
                shared.read_block(1)

    def test_allows_nested_files_with_either_separator(self) -> None:
        (self.root / "nested").mkdir()
        (self.root / "nested" / "relatório.bin").write_bytes(b"contents")
        for filename in ("nested/relatório.bin", "nested\\relatório.bin"):
            with self.subTest(filename=filename), self.repository.open(filename) as shared:
                self.assertEqual(shared.read_block(1), b"contents")

    def test_rejects_missing_files_and_directories(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.repository.open("missing.bin")
        with self.assertRaises(IsADirectoryError):
            self.repository.open(".")

    def test_rejects_traversal_absolute_paths_and_windows_special_names(self) -> None:
        outside = Path(self.directory) / "secret.bin"
        outside.write_bytes(b"secret")
        paths = (
            "../secret.bin", "..\\secret.bin", "nested/../../secret.bin",
            str(outside), "/etc/passwd", "C:\\secret.bin", "C:secret.bin",
            "\\\\server\\share\\secret.bin", "file.bin:stream", "CON", "NUL.txt",
            "folder/COM1", "file.bin.", "file.bin ", ".. /secret.bin",
        )
        for filename in paths:
            with self.subTest(filename=filename), self.assertRaises(PermissionError):
                self.repository.open(filename)
        self.assertEqual(outside.read_bytes(), b"secret")

    def test_rejects_empty_or_null_names(self) -> None:
        for filename in ("", "file\x00.bin"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.repository.open(filename)

    def test_checks_resolved_path_by_components_not_string_prefix(self) -> None:
        outside = Path(self.directory) / "shared-other" / "secret.bin"
        with patch("server.file_repository.Path.resolve", return_value=outside):
            with self.assertRaises(PermissionError):
                self.repository.open("link.bin")

    def test_rejects_symbolic_links_leading_outside_root(self) -> None:
        outside = Path(self.directory) / "secret.bin"
        outside.write_bytes(b"secret")
        link = self.root / "link.bin"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Criação de link simbólico indisponível: {error}")
        with self.assertRaises(PermissionError):
            self.repository.open("link.bin")

    def test_rejects_invalid_block_sequences(self) -> None:
        (self.root / "file.bin").write_bytes(b"contents")
        with self.repository.open("file.bin") as shared:
            for sequence in (0, -1, 2, 1.5, True):
                with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                    shared.read_block(sequence)

    def test_context_manager_closes_the_file(self) -> None:
        (self.root / "file.bin").write_bytes(b"contents")
        with self.repository.open("file.bin") as shared:
            self.assertEqual(shared.read_block(1), b"contents")
        with self.assertRaises(ValueError):
            shared.read_block(1)

    def test_requires_an_existing_directory_as_root(self) -> None:
        with self.assertRaises(FileNotFoundError):
            FileRepository(self.root / "missing")
        regular_file = self.root / "file.bin"
        regular_file.write_bytes(b"contents")
        with self.assertRaises(NotADirectoryError):
            FileRepository(regular_file)
