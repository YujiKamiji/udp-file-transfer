from dataclasses import dataclass
from pathlib import Path

from common.config import validate_network_settings


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 5000
    timeout: float = 1.0
    shared_dir: Path = Path("shared_files")

    def __post_init__(self) -> None:
        validate_network_settings(self.host, self.port, self.timeout)
