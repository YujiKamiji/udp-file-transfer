import os
import stat
from pathlib import Path, PureWindowsPath
from types import TracebackType

from common.protocol.integrity import calculate_checksum
from common.protocol.messages import BLOCK_SIZE, MAX_FILE_SIZE, Metadata


class SharedFile:
    def __init__(self, path: Path) -> None:
        self._file = path.open("rb")
        try:
            information = os.fstat(self._file.fileno())
            if not stat.S_ISREG(information.st_mode):
                raise OSError("apenas arquivos regulares podem ser compartilhados.")
            if information.st_size > MAX_FILE_SIZE:
                raise ValueError("o arquivo excede o tamanho suportado pelo protocolo.")
            size = 0
            checksum = 0
            while data := self._file.read(65536):
                size += len(data)
                if size > MAX_FILE_SIZE:
                    raise ValueError("o arquivo excede o tamanho suportado pelo protocolo.")
                checksum = calculate_checksum(data, checksum)
            if size != information.st_size:
                raise OSError("o tamanho do arquivo mudou durante a leitura.")
            self.metadata = Metadata(size, checksum)
        except BaseException:
            self._file.close()
            raise

    def read_block(self, sequence: int) -> bytes:
        if type(sequence) is not int or not 1 <= sequence <= self.metadata.block_count:
            raise ValueError("número de bloco inválido.")
        offset = (sequence - 1) * BLOCK_SIZE
        expected_size = min(BLOCK_SIZE, self.metadata.file_size - offset)
        self._file.seek(offset)
        data = self._file.read(expected_size)
        if len(data) != expected_size:
            raise OSError("o arquivo foi truncado durante a transferência.")
        return data

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "SharedFile":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class FileRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError("a pasta compartilhada deve ser um diretório.")

    def open(self, filename: str) -> SharedFile:
        if not isinstance(filename, str) or not filename or "\x00" in filename:
            raise ValueError("nome de arquivo inválido.")
        relative = PureWindowsPath(filename)
        if relative.drive or relative.root or ".." in relative.parts:
            raise PermissionError("o caminho deve permanecer dentro da pasta compartilhada.")
        for part in relative.parts:
            if ":" in part or part.endswith((".", " ")) or PureWindowsPath(part).is_reserved():
                raise PermissionError("o caminho contém um nome não permitido.")
        try:
            path = self.root.joinpath(*relative.parts).resolve()
        except RuntimeError as error:
            raise PermissionError("o caminho contém um ciclo de links simbólicos.") from error
        if not path.is_relative_to(self.root):
            raise PermissionError("o caminho aponta para fora da pasta compartilhada.")
        if not path.is_file():
            if path.is_dir():
                raise IsADirectoryError("o caminho solicitado é um diretório.")
            if path.exists():
                raise PermissionError("apenas arquivos regulares podem ser compartilhados.")
            raise FileNotFoundError("arquivo não encontrado.")
        return SharedFile(path)
