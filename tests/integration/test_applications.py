import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from common.protocol.codec import decode_message, encode_message
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ApplicationTests(unittest.TestCase):
    def run_module(self, module: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", module, *arguments],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )

    def start_server(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.output = queue.Queue()
        self.lines = []
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "server", "--port", str(port), "--timeout", "0.05"],
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
        self.wait_for_output("Servidor UDP ativo")
        return port

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
            result = self.run_module("client", filename, "--port", str(receiver.local_address[1]))
            self.assertEqual(result.returncode, 0, result.stderr)
            packet, sender = receiver.receive()
        request = decode_message(packet)
        self.assertEqual(request.message_type, MessageType.GET)
        self.assertEqual(request.sequence, 0)
        self.assertEqual(request.payload.decode("utf-8"), filename)
        self.assertEqual(sender[0], "127.0.0.1")
        self.assertIn(f"transferência {request.transfer_id}", result.stdout)
        self.assertIn("nenhum arquivo foi baixado", result.stdout)

    def test_separate_processes_handle_get_after_invalid_and_unexpected_messages(self) -> None:
        port = self.start_server()
        with UdpTransport(("127.0.0.1", 0)) as sender:
            sender.send_to(b"invalid packet", ("127.0.0.1", port))
            self.wait_for_output("Datagrama inválido")
            sender.send_to(encode_message(Message(MessageType.ACK, 42)), ("127.0.0.1", port))
            self.wait_for_output("Mensagem ACK sem transferência ativa ignorada")

        filename = "relatório de teste.bin"
        result = self.run_module("client", filename, "--port", str(port))
        self.assertEqual(result.returncode, 0, result.stderr)
        line = self.wait_for_output(repr(filename))
        transfer_id = re.search(r"transferência (\d+)", result.stdout)
        self.assertIsNotNone(transfer_id)
        self.assertIn(f"transferência {transfer_id.group(1)}", line)
        self.assertIsNone(self.process.poll())

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
            result = self.run_module("server", "--port", str(occupied.local_address[1]))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Erro ao executar o servidor", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
