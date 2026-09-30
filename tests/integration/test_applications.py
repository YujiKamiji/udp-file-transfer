import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from common.protocol.codec import decode_message, encode_message
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.shared_dir = self.directory / "shared"
        self.output_dir = self.directory / "downloads"
        self.shared_dir.mkdir()

    def run_module(self, module: str, *arguments: str) -> subprocess.CompletedProcess:
        if module == "client" and "--timeout" not in arguments:
            arguments = (*arguments, "--timeout", "0.2")
        return subprocess.run(
            [sys.executable, "-m", module, *arguments],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def start_server(self, timeout: float = 0.2) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.output = queue.Queue()
        self.lines = []
        self.process = subprocess.Popen(
            [
                sys.executable, "-u", "-m", "server", "--port", str(port),
                "--timeout", str(timeout), "--shared-dir", str(self.shared_dir),
            ],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        self.reader = threading.Thread(target=self.read_output, daemon=True)
        self.addCleanup(self.stop_server)
        self.reader.start()
        self.wait_for_output("servidor udp ativo")
        return port

    def start_client(self, *arguments: str) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "client", *arguments],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.addCleanup(self.stop_client, process)
        return process

    def stop_client(self, process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()

    def read_output(self) -> None:
        for line in self.process.stdout:
            self.output.put(line)

    def stop_server(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=3)
        self.process.stdout.close()

    def wait_for_output(self, expected: str) -> str:
        deadline = time.monotonic() + 5
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                line = self.output.get(timeout=remaining)
            except queue.Empty:
                break
            self.lines.append(line)
            if expected in line:
                return line
        self.fail(f"Não encontrei {expected!r} na saída do servidor: {''.join(self.lines)}")

    def test_client_process_sends_a_valid_get_datagram(self) -> None:
        filename = "relatório de teste.bin"
        with UdpTransport(("127.0.0.1", 0)) as receiver:
            result = self.run_module(
                "client", filename, "--port", str(receiver.local_address[1]),
                "--timeout", "0.05", "--output-dir", str(self.output_dir),
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            packet, sender = receiver.receive()
        request = decode_message(packet)
        self.assertEqual(request.message_type, MessageType.GET)
        self.assertEqual(request.sequence, 0)
        self.assertEqual(request.payload.decode("utf-8"), filename)
        self.assertEqual(sender[0], "127.0.0.1")
        self.assertIn(f"transferência {request.transfer_id}", result.stdout)
        self.assertIn("timeout aguardando meta", result.stderr)
        self.assertFalse(self.output_dir.exists())

    def test_separate_processes_handle_get_after_invalid_and_unexpected_messages(self) -> None:
        port = self.start_server()
        with UdpTransport(("127.0.0.1", 0)) as sender:
            sender.send_to(b"invalid packet", ("127.0.0.1", port))
            self.wait_for_output("datagrama inválido")
            sender.send_to(encode_message(Message(MessageType.ACK, 42)), ("127.0.0.1", port))
            self.wait_for_output("mensagem ack sem transferência ativa ignorada")

        filename = "relatório de teste.bin"
        data = bytes(range(256)) * 5
        (self.shared_dir / filename).write_bytes(data)
        result = self.run_module(
            "client", filename, "--port", str(port), "--output-dir", str(self.output_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        line = self.wait_for_output(repr(filename))
        transfer_id = re.search(r"transferência (\d+)", result.stdout)
        self.assertIsNotNone(transfer_id)
        self.assertIn(f"transferência {transfer_id.group(1)}", line)
        self.assertIn("download concluído", result.stdout)
        self.assertNotIn("descartado para simular perda", result.stdout)
        self.assertEqual((self.output_dir / filename).read_bytes(), data)
        self.assertIsNone(self.process.poll())

    def test_recovers_blocks_selected_for_discard_at_command_line(self) -> None:
        filename = "loss-test.bin"
        data = bytes(range(256)) * 28
        (self.shared_dir / filename).write_bytes(data)
        port = self.start_server()
        result = self.run_module(
            "client", filename, "--port", str(port), "--output-dir", str(self.output_dir),
            "--drop-blocks", "1", "3", "7", "3",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output_dir / filename).read_bytes(), data)
        self.assertFalse((self.output_dir / (filename + ".part")).exists())
        self.wait_for_output("concluída:")
        server_output = "".join(self.lines)
        for block in (1, 3, 7):
            with self.subTest(block=block):
                self.assertEqual(
                    result.stdout.count(f"bloco {block} descartado para simular perda; ack não enviado."),
                    1,
                )
                self.assertIn(f"timeout aguardando ack {block}; reenviando data {block}", server_output)
        self.assertIn("download concluído", result.stdout)

    def test_transfers_empty_and_exact_block_files(self) -> None:
        port = self.start_server()
        for filename, data in (("empty.bin", b""), ("block.bin", b"x" * 1024)):
            with self.subTest(filename=filename):
                (self.shared_dir / filename).write_bytes(data)
                result = self.run_module(
                    "client", filename, "--port", str(port),
                    "--output-dir", str(self.output_dir),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.output_dir / filename).read_bytes(), data)
                self.assertFalse((self.output_dir / (filename + ".part")).exists())

    def test_downloads_nested_file_using_only_its_name_in_output_directory(self) -> None:
        (self.shared_dir / "nested").mkdir()
        (self.shared_dir / "nested" / "file.bin").write_bytes(b"nested contents")
        port = self.start_server()
        result = self.run_module(
            "client", "nested/file.bin", "--port", str(port),
            "--output-dir", str(self.output_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output_dir / "file.bin").read_bytes(), b"nested contents")

    def test_reports_missing_forbidden_and_directory_requests(self) -> None:
        (self.directory / "secret.bin").write_bytes(b"secret")
        (self.shared_dir / "folder").mkdir()
        port = self.start_server()
        cases = (
            ("missing.bin", "arquivo não encontrado"),
            ("../secret.bin", "acesso ao arquivo proibido"),
            ("folder", "pedido de arquivo inválido"),
        )
        for filename, error in cases:
            with self.subTest(filename=filename):
                result = self.run_module(
                    "client", filename, "--port", str(port),
                    "--output-dir", str(self.output_dir),
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(error, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(self.output_dir.exists())
                self.assertIsNone(self.process.poll())

    def test_server_waits_for_ack_and_accepts_new_requests_after_timeout(self) -> None:
        (self.shared_dir / "file.bin").write_bytes(b"contents")
        port = self.start_server(timeout=0.2)
        with UdpTransport(("127.0.0.1", 0), timeout=0.05) as client:
            request = Message(MessageType.GET, 42, payload=b"file.bin")
            client.send_to(encode_message(request), ("127.0.0.1", port))
            metadata = decode_message(client.receive()[0])
            self.assertEqual(metadata.message_type, MessageType.META)
            with self.assertRaises(TimeoutError):
                client.receive()
        self.wait_for_output("transferência 42 interrompida")
        result = self.run_module(
            "client", "file.bin", "--port", str(port), "--output-dir", str(self.output_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output_dir / "file.bin").read_bytes(), b"contents")

    def test_transfers_file_larger_than_ten_megabytes_over_udp(self) -> None:
        source = self.shared_dir / "large.bin"
        with source.open("wb") as output:
            for _ in range(161):
                output.write(bytes(range(256)) * 256)
        port = self.start_server()
        result = self.run_module(
            "client", source.name, "--port", str(port), "--timeout", "0.2",
            "--output-dir", str(self.output_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        destination = self.output_dir / source.name
        self.assertGreater(destination.stat().st_size, 10 * 1024 * 1024)
        with source.open("rb") as original, destination.open("rb") as received:
            while data := original.read(65536):
                self.assertEqual(received.read(len(data)), data)
            self.assertEqual(received.read(1), b"")
        self.assertFalse((self.output_dir / "large.bin.part").exists())

    def test_two_client_processes_download_different_files_with_loss_in_one(self) -> None:
        first_data = bytes(range(256)) * 2048
        second_data = b"second file" * 50000
        (self.shared_dir / "first.bin").write_bytes(first_data)
        (self.shared_dir / "second.bin").write_bytes(second_data)
        port = self.start_server(timeout=0.5)
        first = self.start_client(
            "first.bin", "--port", str(port), "--timeout", "0.5",
            "--output-dir", str(self.output_dir / "first"), "--drop-blocks", "1", "3", "7",
        )
        self.wait_for_output("'first.bin'")
        second = self.start_client(
            "second.bin", "--port", str(port), "--timeout", "0.5",
            "--output-dir", str(self.output_dir / "second"),
        )
        first_output, first_error = first.communicate(timeout=30)
        second_output, second_error = second.communicate(timeout=30)
        self.assertEqual(first.returncode, 0, first_error)
        self.assertEqual(second.returncode, 0, second_error)
        self.assertEqual((self.output_dir / "first" / "first.bin").read_bytes(), first_data)
        self.assertEqual((self.output_dir / "second" / "second.bin").read_bytes(), second_data)
        self.assertIn("bloco 3 descartado", first_output)
        self.assertNotIn("descartado", second_output)
        while True:
            try:
                self.lines.append(self.output.get_nowait())
            except queue.Empty:
                break
        server_output = "".join(self.lines)
        first_id = re.search(r"transferência (\d+)", first_output).group(1)
        second_id = re.search(r"transferência (\d+)", second_output).group(1)
        self.assertLess(
            server_output.index("'second.bin'"),
            server_output.index(f"transferência {first_id} concluída"),
        )
        self.assertLess(
            server_output.index(f"transferência {second_id} concluída"),
            server_output.index(f"transferência {first_id} concluída"),
        )
        self.assertIn(f"[transferência {first_id}] timeout aguardando ack 3", server_output)

    def test_clients_with_same_transfer_id_have_independent_acknowledgements(self) -> None:
        (self.shared_dir / "first.bin").write_bytes(b"first contents")
        (self.shared_dir / "second.bin").write_bytes(b"second contents")
        port = self.start_server(timeout=2)
        server = ("127.0.0.1", port)
        with UdpTransport(("127.0.0.1", 0)) as first, UdpTransport(("127.0.0.1", 0)) as second:
            first.send_to(encode_message(Message(MessageType.GET, 42, payload=b"first.bin")), server)
            self.assertEqual(decode_message(first.receive()[0]).message_type, MessageType.META)
            second.send_to(encode_message(Message(MessageType.ACK, 42)), server)
            with self.assertRaises(TimeoutError):
                first.receive(timeout=0.05)
            second.send_to(encode_message(Message(MessageType.GET, 42, payload=b"second.bin")), server)
            self.assertEqual(decode_message(second.receive()[0]).message_type, MessageType.META)
            for client, expected in ((second, b"second contents"), (first, b"first contents")):
                client.send_to(encode_message(Message(MessageType.ACK, 42)), server)
                packet, sender = client.receive()
                self.assertEqual(sender, server)
                message = decode_message(packet)
                self.assertEqual(message.message_type, MessageType.DATA)
                self.assertEqual(message.sequence, 1)
                self.assertEqual(message.payload, expected)
                client.send_to(encode_message(Message(MessageType.ACK, 42, 1)), server)
                finish = decode_message(client.receive()[0])
                self.assertEqual(finish.message_type, MessageType.FIN)
                client.send_to(encode_message(Message(MessageType.ACK, 42, finish.sequence)), server)
                if client is second:
                    with self.assertRaises(TimeoutError):
                        first.receive(timeout=0.05)

    def test_entry_points_offer_help(self) -> None:
        for module in ("client", "server"):
            with self.subTest(module=module):
                result = self.run_module(module, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--port", result.stdout)

    def test_invalid_port_exits_with_argument_error(self) -> None:
        for module, arguments in (("server", []), ("client", ["file.bin"])):
            with self.subTest(module=module):
                result = self.run_module(module, *arguments, "--port", "1024")
                self.assertEqual(result.returncode, 2)
                self.assertIn("1025", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_server_reports_an_occupied_port(self) -> None:
        with UdpTransport(("127.0.0.1", 0)) as occupied:
            result = self.run_module(
                "server", "--port", str(occupied.local_address[1]),
                "--shared-dir", str(self.shared_dir),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("erro ao executar o servidor", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
