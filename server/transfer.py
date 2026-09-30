import time
from queue import Empty, Queue

from common.config import MAX_ATTEMPTS
from common.protocol.codec import ProtocolError, decode_message, encode_message, encode_metadata
from common.protocol.messages import Message, MessageType
from common.transport import Address, UdpTransport
from server.file_repository import SharedFile


def send_and_wait_for_ack(
    transport: UdpTransport, message: Message, client: Address, timeout: float,
    inbox: Queue | None = None,
) -> None:
    packet = encode_message(message)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        transport.send_to(packet, client)
        deadline = time.monotonic() + timeout
        reason = f"timeout aguardando ack {message.sequence}"
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                if inbox is None:
                    incoming = transport.receive(timeout=remaining)
                else:
                    incoming = inbox.get(timeout=remaining)
                if incoming is None:
                    raise InterruptedError("servidor encerrado.")
                received, sender = incoming
            except (TimeoutError, ConnectionResetError, Empty):
                break
            if sender != client:
                continue
            try:
                reply = decode_message(received)
            except ProtocolError:
                continue
            if reply.transfer_id != message.transfer_id:
                continue
            if reply.message_type == MessageType.ACK and reply.sequence == message.sequence:
                return
            if (
                reply.message_type == MessageType.NACK
                and message.message_type == MessageType.DATA
                and reply.sequence == message.sequence
            ):
                reason = f"nack do bloco {message.sequence}"
                break
            if reply.message_type == MessageType.GET and message.message_type == MessageType.META:
                reason = "get repetido"
                break
        if attempt < MAX_ATTEMPTS:
            print(
                f"[transferência {message.transfer_id}] {reason}; reenviando "
                f"{message.message_type.name.lower()} {message.sequence} "
                f"(tentativa {attempt + 1}/{MAX_ATTEMPTS}).",
                flush=True,
            )
    raise TimeoutError(
        f"limite de {MAX_ATTEMPTS} tentativas atingido aguardando ack {message.sequence}."
    )


def send_file(
    transport: UdpTransport,
    shared: SharedFile,
    transfer_id: int,
    client: Address,
    timeout: float,
    inbox: Queue | None = None,
) -> None:
    metadata = Message(MessageType.META, transfer_id, payload=encode_metadata(shared.metadata))
    send_and_wait_for_ack(transport, metadata, client, timeout, inbox)
    total = shared.metadata.block_count
    progress_interval = max(1, (total + 9) // 10)
    for sequence in range(1, total + 1):
        message = Message(MessageType.DATA, transfer_id, sequence, shared.read_block(sequence))
        send_and_wait_for_ack(transport, message, client, timeout, inbox)
        if sequence == 1 or sequence % progress_interval == 0 or sequence == total:
            print(
                f"[transferência {transfer_id}] bloco {sequence}/{total} "
                f"enviado e confirmado ({sequence / total:.0%}).",
                flush=True,
            )
    finish = Message(MessageType.FIN, transfer_id, shared.metadata.block_count + 1)
    send_and_wait_for_ack(transport, finish, client, timeout, inbox)
