import argparse
from collections.abc import Sequence
from pathlib import Path

from server.config import ServerConfig


def parse_args(argv: Sequence[str] | None = None) -> ServerConfig:
    parser = argparse.ArgumentParser(
        prog="python -m server",
        description="inicia o servidor udp e recebe pedidos de arquivos.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="ipv4 local (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="porta udp (padrão: 5000)")
    parser.add_argument("--timeout", type=float, default=1.0, help="timeout em segundos (padrão: 1)")
    parser.add_argument(
        "--shared-dir", type=Path, default=Path("shared_files"),
        help="pasta compartilhada (padrão: shared_files)",
    )
    args = parser.parse_args(argv)
    try:
        return ServerConfig(args.host, args.port, args.timeout, args.shared_dir)
    except ValueError as error:
        parser.error(str(error))
