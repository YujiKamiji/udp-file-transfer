class LossSimulator:
    def __init__(self, blocks: tuple[int, ...] = ()) -> None:
        self._pending = set(blocks)

    def should_drop(self, sequence: int) -> bool:
        if sequence not in self._pending:
            return False
        self._pending.remove(sequence)
        return True
