import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from client.application import main as client_main
from client.cli import parse_args as parse_client_args
from client.config import ClientConfig
from server.application import main as server_main
from server.cli import parse_args as parse_server_args
from server.config import ServerConfig


class CliTests(unittest.TestCase):
    def test_parses_optional_drop_blocks(self) -> None:
        self.assertEqual(parse_client_args(["file.bin"]).drop_blocks, ())
        config = parse_client_args(["file.bin", "--drop-blocks", "3", "7"])
        self.assertEqual(config.drop_blocks, (3, 7))

    def test_rejects_invalid_drop_blocks_before_starting_network(self) -> None:
        for blocks in ([], ["0"], ["-1"], ["text"], ["4294967295"]):
            with self.subTest(blocks=blocks):
                with patch("client.application.run") as run, redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        client_main(["file.bin", "--drop-blocks", *blocks])
                    self.assertEqual(caught.exception.code, 2)
                    run.assert_not_called()

    def test_parses_storage_directories(self) -> None:
        self.assertEqual(
            parse_server_args(["--shared-dir", "my files"]).shared_dir, Path("my files")
        )
        self.assertEqual(
            parse_client_args(["file.bin", "--output-dir", "my downloads"]).output_dir,
            Path("my downloads"),
        )

    def test_parses_server_defaults_and_explicit_arguments(self) -> None:
        self.assertEqual(parse_server_args([]), ServerConfig())
        config = parse_server_args(["--host", "0.0.0.0", "--port", "6000", "--timeout", "0.2"])
        self.assertEqual(config, ServerConfig("0.0.0.0", 6000, 0.2))

    def test_parses_client_defaults_and_explicit_arguments(self) -> None:
        self.assertEqual(parse_client_args(["file.bin"]), ClientConfig("file.bin"))
        config = parse_client_args([
            "arquivo com espaços.bin", "--host", "192.168.1.10",
            "--port", "6000", "--timeout", "0.2",
        ])
        self.assertEqual(config, ClientConfig("arquivo com espaços.bin", "192.168.1.10", 6000, 0.2))

    def test_invalid_arguments_exit_before_starting_network(self) -> None:
        cases = (
            ["--host", "invalid"],
            ["--port", "1024"],
            ["--port", "text"],
            ["--timeout", "nan"],
            ["--timeout", "0"],
            ["--unknown"],
        )
        for main, target, base in (
            (server_main, "server.application.run", []),
            (client_main, "client.application.run", ["file.bin"]),
        ):
            for arguments in cases:
                with self.subTest(target=target, arguments=arguments):
                    with patch(target) as run, redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as caught:
                            main(base + arguments)
                        self.assertEqual(caught.exception.code, 2)
                        run.assert_not_called()

    def test_client_requires_a_filename(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            parse_client_args([])
        self.assertEqual(caught.exception.code, 2)

    def test_help_exits_successfully_without_starting_network(self) -> None:
        for main, target in (
            (server_main, "server.application.run"),
            (client_main, "client.application.run"),
        ):
            with self.subTest(target=target):
                output = io.StringIO()
                with patch(target) as run, redirect_stdout(output):
                    with self.assertRaises(SystemExit) as caught:
                        main(["--help"])
                    self.assertEqual(caught.exception.code, 0)
                    self.assertIn("--host", output.getvalue())
                    run.assert_not_called()

    def test_network_errors_are_reported_without_a_traceback(self) -> None:
        for main, target, arguments in (
            (server_main, "server.application.run", []),
            (client_main, "client.application.run", ["file.bin"]),
        ):
            with self.subTest(target=target):
                output = io.StringIO()
                with patch(target, side_effect=OSError("network failure")), redirect_stderr(output):
                    self.assertEqual(main(arguments), 1)
                self.assertIn("network failure", output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())
