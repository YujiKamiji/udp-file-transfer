import time
from pathlib import Path, PureWindowsPath

from client.file_writer import FileWriter
from client.loss_simulator import LossSimulator
from common.config import MAX_ATTEMPTS
from common.protocol.codec import (
    ProtocolError, decode_message, decode_metadata, encode_message,
)
from common.protocol.messages import ErrorCode, Message, MessageType
from common.transport import Address, UdpTransport


ERROR_MESSAGES = {
    ErrorCode.NOT_FOUND: "arquivo não encontrado no servidor.",
    ErrorCode.FORBIDDEN: "acesso ao arquivo proibido pelo servidor.",
    ErrorCode.BAD_REQUEST: "pedido de arquivo inválido.",
    ErrorCode.IO_ERROR: "o servidor não conseguiu ler o arquivo.",
}


def receive_expected(
    transport: UdpTransport,
    server: Address,
    transfer_id: int,
    message_type: MessageType,
    sequence: int,
    timeout: float,
    loss_simulator: LossSimulator | None = None,
) -> Message:
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            packet, sender = transport.receive(timeout=remaining)
        except TimeoutError:
            break
        if sender != server:
            continue
        try:
            message = decode_message(packet)
        except ProtocolError:
            if message_type == MessageType.DATA:
                request = Message(MessageType.NACK, transfer_id, sequence)
                transport.send_to(encode_message(request), server)
                print(
                    f"[transferência {transfer_id}] pacote inválido; solicitando bloco {sequence}.",
                    flush=True,
                )
            continue
        if message.transfer_id != transfer_id:
            continue
        if (
            message.message_type == MessageType.DATA
            and loss_simulator is not None
            and loss_simulator.should_drop(message.sequence)
        ):
            print(
                f"[transferência {transfer_id}] bloco {message.sequence} descartado "
                "para simular perda; ack não enviado.",
                flush=True,
            )
            continue
        if message.message_type == MessageType.ERROR:
            raise OSError(ERROR_MESSAGES[ErrorCode(message.payload[0])])
        if message.message_type == message_type and message.sequence == sequence:
            return message
        if message_type != MessageType.META and (
            message.message_type == MessageType.META
            or (message.message_type == MessageType.DATA and message.sequence < sequence)
        ):
            acknowledgement = Message(MessageType.ACK, transfer_id, message.sequence)
            transport.send_to(encode_message(acknowledgement), server)
            print(
                f"[transferência {transfer_id}] {message.message_type.name.lower()} "
                f"{message.sequence} repetido; ack reenviado.",
                flush=True,
            )
        elif message_type == MessageType.DATA and message.message_type in (MessageType.DATA, MessageType.FIN):
            request = Message(MessageType.NACK, transfer_id, sequence)
            transport.send_to(encode_message(request), server)
    raise TimeoutError(f"timeout aguardando {message_type.name.lower()} {sequence} do servidor.")


def request_metadata(
    transport: UdpTransport, server: Address, request: Message, timeout: float
) -> Message:
    packet = encode_message(request)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        transport.send_to(packet, server)
        try:
            return receive_expected(
                transport, server, request.transfer_id, MessageType.META, 0, timeout
            )
        except TimeoutError:
            if attempt == MAX_ATTEMPTS:
                raise
            print(
                f"[transferência {request.transfer_id}] timeout aguardando meta; "
                f"reenviando get (tentativa {attempt + 1}/{MAX_ATTEMPTS}).",
                flush=True,
            )


def confirm_finish(
    transport: UdpTransport, server: Address, transfer_id: int, sequence: int, timeout: float
) -> None:
    acknowledgement = encode_message(Message(MessageType.ACK, transfer_id, sequence))
    transport.send_to(acknowledgement, server)
    deadline = time.monotonic() + MAX_ATTEMPTS * timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            packet, sender = transport.receive(timeout=remaining)
        except (TimeoutError, ConnectionResetError):
            return
        if sender != server:
            continue
        try:
            message = decode_message(packet)
        except ProtocolError:
            continue
        if (
            message.message_type == MessageType.FIN
            and message.transfer_id == transfer_id
            and message.sequence == sequence
        ):
            transport.send_to(acknowledgement, server)
            print(f"[transferência {transfer_id}] fin repetido; ack reenviado.", flush=True)


def receive_file(
    transport: UdpTransport,
    server: Address,
    request: Message,
    output_dir: Path,
    timeout: float,
    drop_blocks: tuple[int, ...] = (),
) -> Path:
    loss_simulator = LossSimulator(drop_blocks)
    reply = request_metadata(transport, server, request, timeout)
    metadata = decode_metadata(reply.payload)
    filename = PureWindowsPath(request.payload.decode("utf-8")).name
    if (
        not filename or filename.endswith((".", " "))
        or ":" in filename or PureWindowsPath(filename).is_reserved()
    ):
        raise ValueError("nome de arquivo inválido para gravação local.")
    destination = Path(output_dir) / filename
    with FileWriter(destination, metadata) as writer:
        transport.send_to(encode_message(Message(MessageType.ACK, request.transfer_id)), server)
        total = metadata.block_count
        progress_interval = max(1, (total + 9) // 10)
        for sequence in range(1, total + 1):
            message = receive_expected(
                transport, server, request.transfer_id, MessageType.DATA, sequence,
                timeout * (MAX_ATTEMPTS + 1),
                loss_simulator=loss_simulator,
            )
            writer.write_block(sequence, message.payload)
            acknowledgement = Message(MessageType.ACK, request.transfer_id, sequence)
            transport.send_to(encode_message(acknowledgement), server)
            if sequence == 1 or sequence % progress_interval == 0 or sequence == total:
                print(
                    f"[transferência {request.transfer_id}] bloco {sequence}/{total} "
                    f"recebido e validado ({sequence / total:.0%}).",
                    flush=True,
                )
        final_sequence = metadata.block_count + 1
        receive_expected(
            transport, server, request.transfer_id, MessageType.FIN, final_sequence,
            timeout * (MAX_ATTEMPTS + 1),
        )
        writer.finalize()
        confirm_finish(transport, server, request.transfer_id, final_sequence, timeout)
    return destination
