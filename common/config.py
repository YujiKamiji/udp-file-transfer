import math
from ipaddress import IPv4Address


def validate_network_settings(host: str, port: int, timeout: float) -> None:
    if not isinstance(host, str):
        raise ValueError("O endereço deve ser um IPv4 válido.")
    try:
        IPv4Address(host)
    except ValueError as error:
        raise ValueError("O endereço deve ser um IPv4 válido.") from error
    if type(port) is not int or not 1024 < port <= 65535:
        raise ValueError("A porta deve ser um inteiro entre 1025 e 65535.")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("O timeout deve ser um número positivo e finito.")
