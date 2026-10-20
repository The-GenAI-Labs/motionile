from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.media import EPOCH, World, fake_session
from tests.fakes.render_jobs import FakeSpeech, FakeToolchain, FlakyStorage, InMemoryRenderJobStore
from tests.fakes.settings import make_settings
from tests.fakes.storage import StoredObject
from tests.unit.modules.media.support import USER_A

from motionile.core.clock import SystemClock
from motionile.core.config import RenderSettings
from motionile.core.ids import new_id
from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.engine.audio.audio_validation import ValidatedAudio
from motionile.engine.audio.providers.fake import FakeTranscriber
from motionile.modules.media.assets import AssetService
from motionile.modules.media.domain import RenderSource
from motionile.modules.media.models import MusicTrack, Render
from motionile.modules.media.music import MusicService
from motionile.modules.media.music_audio import ProcessedMusic
from motionile.modules.media.pipeline import PipelineDeps, RenderPipeline
from motionile.modules.media.render_commands import AudioCheck, RenderCommandPorts, RenderCommands
from motionile.modules.media.render_events import RenderEvents, render_channel
from motionile.modules.media.render_options import RenderOptions, RenderOptionsRequest, ResolvedVoice, stored_options
from motionile.modules.media.render_repository import RenderJobStore

VOICE = ResolvedVoice(voice_id=UUID(int=7), provider="fake", provider_voice_id="fake-voice-aria", language="en")
COMPOSITION = '<html><body><section data-scene="intro"></section><section data-scene="outro"></section></body></html>'
SCENES = [
    {"sceneId": "intro", "text": "Every video begins with a question."},
    {"sceneId": "outro", "text": "Then it answers it."},
]
MUSIC_KEY = "music/track.m4a"


class StubMusicProcessor:
    async def process(self, data: bytes) -> ProcessedMusic:
        return ProcessedMusic(data, 10_000)


async def accept_audio(data: bytes) -> ValidatedAudio:
    return ValidatedAudio("wav", "wav", "pcm_s16le", 1000, 16000, 1, len(data))


def request_options(**overrides: object) -> RenderOptionsRequest:
    payload: dict[str, object] = {
        "aspects": ["16:9", "9:16"],
        "fps": 24,
        "narration": {"mode": "synthesize", "voiceId": str(VOICE.voice_id), "scenes": SCENES},
        **overrides,
    }
    return RenderOptionsRequest.model_validate(payload)


def render_options(**overrides: object) -> RenderOptions:
    return stored_options(request_options(**overrides), VOICE, 24)


@dataclass
class Rig:
    world: World
    storage: FlakyStorage
    toolchain: FakeToolchain
    speech: FakeSpeech
    redis: FakeRedis
    events: RenderEvents
    assets: AssetService
    music: MusicService
    deps: PipelineDeps
    pipeline: RenderPipeline
    dispatched: list[UUID] = field(default_factory=list[UUID])

    def job_store(self, session: AsyncSession) -> RenderJobStore:
        del session
        return InMemoryRenderJobStore(self.world)

    def commands(self, audio_check: AudioCheck = accept_audio) -> RenderCommands:
        return RenderCommands(
            RenderCommandPorts(
                assets=self.assets,
                music=self.music,
                storage=self.storage,
                events=self.events,
                settings=self.deps.settings,
                clock=self.deps.clock,
                dispatch=lambda _session, render_id: self.dispatched.append(render_id),
                audio_check=audio_check,
                speech=self.speech,
                transcriber=FakeTranscriber(),
                store_factory=self.job_store,
                normalizer=self.toolchain,
            )
        )

    def add_track(self, *, active: bool = True) -> MusicTrack:
        audio = self.world.add_asset(MUSIC_KEY, owner=None, kind="audio")
        track = MusicTrack(
            id=new_id(),
            title="Slow dawn",
            audio_asset_id=audio.id,
            mood="calm",
            bpm=80,
            duration_ms=60_000,
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution_text="Slow dawn",
            is_active=active,
            created_by_user_id=None,
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self.world.tracks[track.id] = track
        self.storage.objects[MUSIC_KEY] = StoredObject(b"music", "audio/mp4", {}, EPOCH)
        return track

    async def queue_render(
        self,
        options: RenderOptions | None = None,
        html: str = COMPOSITION,
        *,
        owner: UUID = USER_A,
        audio_uploads: Mapping[str, bytes] | None = None,
    ) -> UUID:
        view = await self.commands().create_render(
            fake_session(), owner, html, options or render_options(), RenderSource.JOB, audio_uploads=audio_uploads
        )
        return view.id

    def render(self, render_id: UUID) -> Render:
        return self.world.renders[render_id]

    def channel(self, render_id: UUID) -> str:
        return render_channel(RedisKeyBuilder("t"), render_id)


def build_rig(tmp_path: Path, *, stall_seconds: int = 900, max_duration_ms: int = 120_000) -> Rig:
    world = World()
    storage = FlakyStorage()
    settings = make_settings().model_copy(
        update={
            "render": RenderSettings(
                work_directory=tmp_path,
                stall_seconds=stall_seconds,
                stage_timeout_seconds=600,
                max_duration_ms=max_duration_ms,
            )
        }
    )
    redis = FakeRedis()
    events = RenderEvents(RedisStore(redis, RedisKeyBuilder("t")))
    assets = AssetService(storage, world.asset_store)
    music = MusicService(
        assets, storage, StubMusicProcessor(), preview_ttl=timedelta(seconds=60), store_factory=world.music_store
    )
    toolchain = FakeToolchain()
    speech = FakeSpeech()

    def toolchain_for(fps: int) -> FakeToolchain:
        toolchain.fps = fps
        return toolchain

    def job_store(session: AsyncSession) -> RenderJobStore:
        del session
        return InMemoryRenderJobStore(world)

    deps = PipelineDeps(
        transaction=world.transaction,
        storage=storage,
        assets=assets,
        speech=speech,
        music=music,
        transcriber=FakeTranscriber(),
        toolchain_for=toolchain_for,
        events=events,
        settings=settings,
        clock=SystemClock(),
        store_factory=job_store,
    )
    return Rig(world, storage, toolchain, speech, redis, events, assets, music, deps, RenderPipeline(deps))
