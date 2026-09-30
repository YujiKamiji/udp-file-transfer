import sys
from collections.abc import Sequence

from common.transport import UdpTransport
from server.cli import parse_args
from server.config import ServerConfig
from server.dispatcher import TransferDispatcher
from server.file_repository import FileRepository


def run(config: ServerConfig) -> None:
    repository = FileRepository(config.shared_dir)
    with UdpTransport((config.host, config.port), config.timeout) as transport:
        print(f"servidor udp ativo em {config.host}:{config.port}.", flush=True)
        print(f"pasta compartilhada: {repository.root}", flush=True)
        dispatcher = TransferDispatcher(transport, repository, config.timeout)
        try:
            while True:
                try:
                    packet, sender = transport.receive()
                except (TimeoutError, ConnectionResetError):
                    continue
                dispatcher.dispatch(packet, sender)
        finally:
            dispatcher.close()


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        run(config)
    except KeyboardInterrupt:
        print("\nservidor encerrado.")
    except (OSError, OverflowError) as error:
        print(f"erro ao executar o servidor: {error}", file=sys.stderr)
        return 1
    return 0
