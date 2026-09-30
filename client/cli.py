import argparse
from collections.abc import Sequence
from pathlib import Path

from client.config import ClientConfig


def parse_args(argv: Sequence[str] | None = None) -> ClientConfig:
    parser = argparse.ArgumentParser(
        prog="python -m client",
        description="baixa um arquivo do servidor udp.",
    )
    parser.add_argument("filename", help="nome do arquivo no servidor")
    parser.add_argument("--host", default="127.0.0.1", help="ipv4 do servidor (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="porta udp (padrão: 5000)")
    parser.add_argument("--timeout", type=float, default=1.0, help="timeout em segundos (padrão: 1)")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("downloads"),
        help="pasta de destino (padrão: downloads)",
    )
    parser.add_argument(
        "--drop-blocks", type=int, nargs="+", default=[], metavar="bloco",
        help="descarta a primeira chegada dos blocos indicados (exemplo: --drop-blocks 3 7)",
    )
    args = parser.parse_args(argv)
    try:
        return ClientConfig(
            args.filename, args.host, args.port, args.timeout,
            args.output_dir, tuple(args.drop_blocks),
        )
    except ValueError as error:
        parser.error(str(error))
