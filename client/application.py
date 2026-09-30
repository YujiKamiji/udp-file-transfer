import secrets
import sys
from collections.abc import Sequence

from client.cli import parse_args
from client.config import ClientConfig
from client.transfer import receive_file
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport


def run(config: ClientConfig) -> None:
    request = Message(
        MessageType.GET,
        secrets.randbits(32),
        payload=config.filename.encode("utf-8"),
    )
    print(
        f"solicitando {config.filename!r} de {config.host}:{config.port} "
        f"(transferência {request.transfer_id}).",
        flush=True,
    )
    with UdpTransport(("0.0.0.0", 0), config.timeout) as transport:
        destination = receive_file(
            transport, (config.host, config.port), request, config.output_dir,
            config.timeout, config.drop_blocks,
        )
    print(f"download concluído: {destination.resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        run(config)
    except KeyboardInterrupt:
        print("\ncliente interrompido.", file=sys.stderr)
        return 130
    except (OSError, ValueError, OverflowError) as error:
        print(f"erro ao executar o cliente: {error}", file=sys.stderr)
        return 1
    return 0
