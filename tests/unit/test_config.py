import unittest

from client.config import ClientConfig
from server.config import ServerConfig


class ConfigTests(unittest.TestCase):
    def test_drop_blocks_must_be_valid_block_numbers(self) -> None:
        self.assertEqual(ClientConfig("file.bin", drop_blocks=(1, 3, 7)).drop_blocks, (1, 3, 7))
        for block in (0, -1, True, 1.5, "3", 2**32 - 1):
            with self.subTest(block=block), self.assertRaises(ValueError):
                ClientConfig("file.bin", drop_blocks=(block,))

    def test_defaults_and_valid_port_boundaries(self) -> None:
        self.assertEqual(ServerConfig().host, "127.0.0.1")
        self.assertEqual(ServerConfig().timeout, 1.0)
        self.assertEqual(ClientConfig("file.bin").port, 5000)
        for port in (1025, 65535):
            with self.subTest(port=port):
                self.assertEqual(ServerConfig(port=port).port, port)
                self.assertEqual(ClientConfig("file.bin", port=port).port, port)

    def test_rejects_invalid_network_settings_in_both_apps(self) -> None:
        cases = [
            {"host": "localhost"},
            {"host": "::1"},
            {"host": "256.1.2.3"},
            {"host": ""},
            {"host": 123},
            {"port": 0},
            {"port": 1024},
            {"port": 65536},
            {"port": 5000.5},
            {"port": True},
            {"timeout": 0},
            {"timeout": -1},
            {"timeout": float("nan")},
            {"timeout": float("inf")},
            {"timeout": True},
        ]
        for settings in cases:
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    ServerConfig(**settings)
                with self.assertRaises(ValueError):
                    ClientConfig("file.bin", **settings)

    def test_wildcard_address_is_only_accepted_for_server(self) -> None:
        self.assertEqual(ServerConfig(host="0.0.0.0").host, "0.0.0.0")
        with self.assertRaises(ValueError):
            ClientConfig("file.bin", host="0.0.0.0")

    def test_filename_limit_is_measured_in_utf8_bytes(self) -> None:
        self.assertEqual(ClientConfig("é" * 512).filename, "é" * 512)
        for filename in ("", "file\x00.bin", "a" * 1025, "é" * 513):
            with self.subTest(filename=filename[:20]):
                with self.assertRaises(ValueError):
                    ClientConfig(filename)

    def test_does_not_require_the_remote_file_to_exist_locally(self) -> None:
        self.assertEqual(ClientConfig("remote/file.bin").filename, "remote/file.bin")
