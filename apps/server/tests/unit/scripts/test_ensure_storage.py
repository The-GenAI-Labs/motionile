import pytest
from botocore.exceptions import EndpointConnectionError
from tests.fakes.settings import deployed_settings

from motionile.scripts import ensure_storage
from motionile.scripts.ensure_storage import EXIT_REFUSED, ensure_with_retries, main


class FlakyStorage:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def ensure_bucket(self) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise EndpointConnectionError(endpoint_url="http://minio:9000")


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_it_retries_until_the_storage_answers() -> None:
    storage = FlakyStorage(failures=2)
    sleeps = Sleeps()

    await ensure_with_retries(storage, attempts=5, delay_seconds=0.5, sleep=sleeps)

    assert storage.calls == 3
    assert sleeps.delays == [0.5, 0.5]


async def test_it_gives_up_after_the_last_attempt() -> None:
    storage = FlakyStorage(failures=10)
    sleeps = Sleeps()

    with pytest.raises(EndpointConnectionError):
        await ensure_with_retries(storage, attempts=3, delay_seconds=1.0, sleep=sleeps)

    assert storage.calls == 3
    assert len(sleeps.delays) == 2


async def test_it_does_not_sleep_when_the_first_attempt_works() -> None:
    storage = FlakyStorage(failures=0)
    sleeps = Sleeps()

    await ensure_with_retries(storage, sleep=sleeps)

    assert storage.calls == 1
    assert sleeps.delays == []


def test_it_refuses_to_run_outside_local_and_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ensure_storage, "get_settings", deployed_settings)

    assert main() == EXIT_REFUSED


def test_it_creates_the_bucket_in_local_environments(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = FlakyStorage(failures=0)

    class StorageFactory:
        @staticmethod
        def from_settings(_: object) -> FlakyStorage:
            return storage

    monkeypatch.setattr(ensure_storage, "S3Storage", StorageFactory)

    assert main() == 0
    assert storage.calls == 1
