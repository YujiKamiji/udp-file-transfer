import secrets
import sys
from collections.abc import Sequence

from client.cli import parse_args
from client.config import ClientConfig
from common.protocol.codec import encode_message
from common.protocol.messages import Message, MessageType
from common.transport import UdpTransport


def run(config: ClientConfig) -> None:
    request = Message(
        MessageType.GET,
        secrets.randbits(32),
        payload=config.filename.encode("utf-8"),
    )
    with UdpTransport(("0.0.0.0", 0), config.timeout) as transport:
        transport.send_to(encode_message(request), (config.host, config.port))
    print(
        f"Pedido enviado para {config.host}:{config.port}: {config.filename!r} "
        f"(transferência {request.transfer_id})."
    )
    print("O recebimento pelo servidor ainda não é confirmado e nenhum arquivo foi baixado.")


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        run(config)
    except KeyboardInterrupt:
        print("\nCliente interrompido.", file=sys.stderr)
        return 130
    except (OSError, OverflowError) as error:
        print(f"Erro ao executar o cliente: {error}", file=sys.stderr)
        return 1
    return 0
