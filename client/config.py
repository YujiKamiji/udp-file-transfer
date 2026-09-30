from dataclasses import dataclass

from common.config import validate_network_settings
from common.protocol.messages import BLOCK_SIZE


@dataclass(frozen=True)
class ClientConfig:
    filename: str
    host: str = "127.0.0.1"
    port: int = 5000
    timeout: float = 1.0

    def __post_init__(self) -> None:
        validate_network_settings(self.host, self.port, self.timeout)
        if self.host == "0.0.0.0":
            raise ValueError("Informe o IPv4 do servidor; 0.0.0.0 não é um destino.")
        if not isinstance(self.filename, str) or not self.filename or "\x00" in self.filename:
            raise ValueError("O nome do arquivo não pode ser vazio ou conter bytes nulos.")
        if len(self.filename.encode("utf-8")) > BLOCK_SIZE:
            raise ValueError("O nome do arquivo deve ocupar no máximo 1024 bytes em UTF-8.")
