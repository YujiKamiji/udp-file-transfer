import argparse
from collections.abc import Sequence

from client.config import ClientConfig


def parse_args(argv: Sequence[str] | None = None) -> ClientConfig:
    parser = argparse.ArgumentParser(
        prog="python -m client",
        description="Envia um pedido de arquivo ao servidor UDP.",
    )
    parser.add_argument("filename", help="Nome do arquivo no servidor")
    parser.add_argument("--host", default="127.0.0.1", help="IPv4 do servidor (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Porta UDP (padrão: 5000)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Timeout em segundos (padrão: 1)")
    args = parser.parse_args(argv)
    try:
        return ClientConfig(args.filename, args.host, args.port, args.timeout)
    except ValueError as error:
        parser.error(str(error))
