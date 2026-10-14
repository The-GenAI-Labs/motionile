from dataclasses import dataclass


@dataclass
class FakeProbe:
    failure: Exception | None = None
    calls: int = 0

    async def ping(self, timeout_seconds: float) -> None:
        self.calls += 1
        assert timeout_seconds > 0
        if self.failure is not None:
            raise self.failure
