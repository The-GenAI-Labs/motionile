from datetime import timedelta

import structlog

from motionile.core.clock import Clock
from motionile.modules.media import AssetInUseError, AssetNotFoundError, AssetService
from motionile.modules.voices.domain import VoiceFailureCode
from motionile.modules.voices.ports import Transaction
from motionile.modules.voices.repository import StoreFactory
from motionile.modules.voices.runner import CloneRunner

logger = structlog.get_logger(__name__)

BATCH_SIZE = 100


class VoiceMaintenance:
    def __init__(
        self,
        transaction: Transaction,
        store_factory: StoreFactory,
        assets: AssetService,
        runner: CloneRunner,
        clock: Clock,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._assets = assets
        self._runner = runner
        self._clock = clock

    async def purge_abandoned_samples(self, older_than: timedelta) -> int:
        cutoff = self._clock.now() - older_than
        removed = 0
        while True:
            deleted = 0
            async with self._transaction() as session:
                rows = await self._store_factory(session).abandoned_sample_assets(cutoff, BATCH_SIZE)
                for asset in rows:
                    try:
                        await self._assets.delete(session, asset.owner_user_id, asset.id)
                    except (AssetNotFoundError, AssetInUseError):
                        continue
                    deleted += 1
            removed += deleted
            if deleted == 0 or len(rows) < BATCH_SIZE:
                return removed

    async def fail_stalled_clones(self, older_than: timedelta) -> int:
        cutoff = self._clock.now() - older_than
        async with self._transaction() as session:
            rows = await self._store_factory(session).stalled_pending(cutoff, BATCH_SIZE)
        for voice in rows:
            await self._runner.fail(voice.id, VoiceFailureCode.CLONE_STALLED)
        return len(rows)
