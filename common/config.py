import math
from ipaddress import IPv4Address


MAX_ATTEMPTS = 5


def validate_network_settings(host: str, port: int, timeout: float) -> None:
    if not isinstance(host, str):
        raise ValueError("o endereço deve ser um ipv4 válido.")
    try:
        IPv4Address(host)
    except ValueError as error:
        raise ValueError("o endereço deve ser um ipv4 válido.") from error
    if type(port) is not int or not 1024 < port <= 65535:
        raise ValueError("a porta deve ser um inteiro entre 1025 e 65535.")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("o timeout deve ser um número positivo e finito.")
