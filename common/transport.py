import socket
from types import TracebackType


Address = tuple[str, int]


class UdpTransport:
    def __init__(self, local_address: Address, timeout: float = 1.0) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.settimeout(timeout)
            self._socket.bind(local_address)
        except (OSError, ValueError, TypeError, OverflowError):
            self._socket.close()
            raise

    @property
    def local_address(self) -> Address:
        return self._socket.getsockname()

    def send_to(self, data: bytes, destination: Address) -> None:
        self._socket.sendto(data, destination)

    def receive(self) -> tuple[bytes, Address]:
        return self._socket.recvfrom(65535)

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> "UdpTransport":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
