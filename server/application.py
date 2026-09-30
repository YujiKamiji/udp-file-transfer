import sys
from collections.abc import Sequence

from common.protocol.codec import ProtocolError, decode_message
from common.protocol.messages import MessageType
from common.transport import UdpTransport
from server.cli import parse_args
from server.config import ServerConfig


def run(config: ServerConfig) -> None:
    with UdpTransport((config.host, config.port), config.timeout) as transport:
        print(f"Servidor UDP ativo em {config.host}:{config.port}.", flush=True)
        print("Nesta etapa, os pedidos são registrados; arquivos ainda não são enviados.", flush=True)
        while True:
            try:
                packet, sender = transport.receive()
            except TimeoutError:
                continue
            try:
                message = decode_message(packet)
            except ProtocolError:
                print(f"Datagrama inválido de {sender[0]}:{sender[1]} ignorado.", flush=True)
                continue
            if message.message_type != MessageType.GET:
                print(f"Mensagem {message.message_type.name} sem transferência ativa ignorada.", flush=True)
                continue
            filename = message.payload.decode("utf-8")
            print(
                f"Pedido de {sender[0]}:{sender[1]}: {filename!r} "
                f"(transferência {message.transfer_id}).",
                flush=True,
            )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    try:
        run(config)
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    except (OSError, OverflowError) as error:
        print(f"Erro ao executar o servidor: {error}", file=sys.stderr)
        return 1
    return 0
