import time
from queue import Queue
from threading import Lock, Thread

from common.config import MAX_ATTEMPTS
from common.protocol.codec import ProtocolError, decode_message, encode_message
from common.protocol.messages import ErrorCode, Message, MessageType
from common.transport import Address, UdpTransport
from server.file_repository import FileRepository
from server.transfer import send_file


class TransferDispatcher:
    def __init__(self, transport: UdpTransport, repository: FileRepository, timeout: float) -> None:
        self.transport = transport
        self.repository = repository
        self.timeout = timeout
        self._active: dict[tuple[Address, int], tuple[Queue, Thread]] = {}
        self._completed: dict[tuple[Address, int], float] = {}
        self._lock = Lock()

    def dispatch(self, packet: bytes, sender: Address) -> None:
        try:
            message = decode_message(packet)
        except ProtocolError:
            print(f"datagrama inválido de {sender[0]}:{sender[1]} ignorado.", flush=True)
            return
        key = (sender, message.transfer_id)
        with self._lock:
            now = time.monotonic()
            self._completed = {key: expiry for key, expiry in self._completed.items() if expiry > now}
            if key in self._completed:
                return
            if key in self._active:
                inbox, _ = self._active[key]
                if message.message_type in (MessageType.GET, MessageType.ACK, MessageType.NACK):
                    inbox.put((packet, sender))
                return
            if message.message_type != MessageType.GET:
                print(f"mensagem {message.message_type.name.lower()} sem transferência ativa ignorada.", flush=True)
                return
            inbox = Queue()
            worker = Thread(target=self._serve, args=(message, sender, inbox))
            self._active[key] = (inbox, worker)
            worker.start()

    def _serve(self, request: Message, client: Address, inbox: Queue) -> None:
        key = (client, request.transfer_id)
        filename = request.payload.decode("utf-8")
        completed = False
        print(
            f"pedido de {client[0]}:{client[1]}: {filename!r} "
            f"(transferência {request.transfer_id}).",
            flush=True,
        )
        try:
            with self.repository.open(filename) as shared:
                send_file(self.transport, shared, request.transfer_id, client, self.timeout, inbox)
            completed = True
            print(f"transferência {request.transfer_id} concluída: {filename!r}.", flush=True)
        except (TimeoutError, InterruptedError) as error:
            print(f"transferência {request.transfer_id} interrompida: {error}", flush=True)
        except (OSError, ValueError) as error:
            if isinstance(error, FileNotFoundError):
                code = ErrorCode.NOT_FOUND
            elif isinstance(error, PermissionError):
                code = ErrorCode.FORBIDDEN
            elif isinstance(error, (IsADirectoryError, ValueError)):
                code = ErrorCode.BAD_REQUEST
            else:
                code = ErrorCode.IO_ERROR
            reply = Message(MessageType.ERROR, request.transfer_id, payload=bytes([code]))
            try:
                self.transport.send_to(encode_message(reply), client)
            except OSError as send_error:
                print(f"não foi possível enviar o erro ao cliente: {send_error}", flush=True)
            print(f"transferência {request.transfer_id}: {error}", flush=True)
        finally:
            with self._lock:
                self._active.pop(key, None)
                if completed:
                    self._completed[key] = time.monotonic() + self.timeout * (MAX_ATTEMPTS + 1)

    def close(self) -> None:
        with self._lock:
            active = list(self._active.values())
            for inbox, _ in active:
                inbox.put(None)
        for _, worker in active:
            worker.join()
