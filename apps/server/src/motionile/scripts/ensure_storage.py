import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Protocol

from botocore.exceptions import BotoCoreError, ClientError

from motionile.core.config import get_settings
from motionile.core.storage.s3 import S3Storage

ATTEMPTS = 30
DELAY_SECONDS = 2.0
EXIT_REFUSED = 2
REFUSAL = "The storage bucket is only created automatically in local and CI environments."

type Sleep = Callable[[float], Awaitable[None]]


class BucketEnsurer(Protocol):
    async def ensure_bucket(self) -> None: ...


async def ensure_with_retries(
    storage: BucketEnsurer,
    *,
    attempts: int = ATTEMPTS,
    delay_seconds: float = DELAY_SECONDS,
    sleep: Sleep = asyncio.sleep,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await storage.ensure_bucket()
        except (BotoCoreError, ClientError, OSError):
            if attempt == attempts:
                raise
            await sleep(delay_seconds)
        else:
            return


def main() -> int:
    settings = get_settings()
    if not settings.test_routes_enabled:
        sys.stderr.write(f"{REFUSAL}\n")
        return EXIT_REFUSED
    asyncio.run(ensure_with_retries(S3Storage.from_settings(settings.storage)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
