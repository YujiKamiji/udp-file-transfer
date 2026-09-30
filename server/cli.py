import argparse
from collections.abc import Sequence

from server.config import ServerConfig


def parse_args(argv: Sequence[str] | None = None) -> ServerConfig:
    parser = argparse.ArgumentParser(
        prog="python -m server",
        description="Inicia o servidor UDP e recebe pedidos de arquivos.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="IPv4 local (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Porta UDP (padrão: 5000)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Timeout em segundos (padrão: 1)")
    args = parser.parse_args(argv)
    try:
        return ServerConfig(args.host, args.port, args.timeout)
    except ValueError as error:
        parser.error(str(error))
