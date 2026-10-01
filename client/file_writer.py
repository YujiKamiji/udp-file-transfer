import os
from pathlib import Path
from types import TracebackType

from common.protocol.codec import encode_metadata
from common.protocol.integrity import calculate_checksum
from common.protocol.messages import BLOCK_SIZE, Metadata


class FileWriter:
    def __init__(self, destination: Path, metadata: Metadata) -> None:
        encode_metadata(metadata)
        self.destination = Path(destination)
        self.metadata = metadata
        self._next_sequence = 1
        self._finalized = False
        if os.path.lexists(self.destination):
            raise FileExistsError("já existe um arquivo no destino.")
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.partial_path = self.destination.with_name(self.destination.name + ".part")
        self._file = self.partial_path.open("x+b")

    def write_block(self, sequence: int, data: bytes) -> None:
        if self._file.closed:
            raise ValueError("a gravação já foi encerrada.")
        if type(sequence) is not int or sequence != self._next_sequence:
            raise ValueError("o bloco deve corresponder à próxima sequência esperada.")
        if sequence > self.metadata.block_count:
            raise ValueError("todos os blocos esperados já foram gravados.")
        expected_size = min(
            BLOCK_SIZE, self.metadata.file_size - (sequence - 1) * BLOCK_SIZE
        )
        if not isinstance(data, bytes) or len(data) != expected_size:
            raise ValueError("o tamanho do bloco não corresponde aos metadados.")
        self._file.write(data)
        self._next_sequence += 1

    def finalize(self) -> Path:
        if self._finalized:
            return self.destination
        if self._file.closed:
            raise ValueError("a gravação já foi encerrada.")
        if self._next_sequence != self.metadata.block_count + 1:
            raise ValueError("o arquivo ainda está incompleto.")
        self._file.flush()
        self._file.seek(0)
        size = 0
        checksum = 0
        while data := self._file.read(65536):
            size += len(data)
            checksum = calculate_checksum(data, checksum)
        if size != self.metadata.file_size or checksum != self.metadata.checksum:
            raise ValueError("o tamanho ou crc32 do arquivo recebido está incorreto.")
        try:
            self._file.close()
            if os.path.lexists(self.destination):
                raise FileExistsError("já existe um arquivo no destino.")
            self.partial_path.rename(self.destination)
        except OSError:
            self.partial_path.unlink(missing_ok=True)
            raise
        self._finalized = True
        return self.destination

    def close(self) -> None:
        if not self._file.closed:
            try:
                self._file.close()
            finally:
                self.partial_path.unlink(missing_ok=True)

    def __enter__(self) -> "FileWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
