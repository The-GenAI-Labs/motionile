from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from tests.fakes.media import World
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import NOW, USER_A

from motionile.core.clock import FrozenClock
from motionile.core.config import AppEnv, AppSettings, ProvidersMode, Settings
from motionile.engine.audio.cache_key import tts_cache_key
from motionile.engine.audio.models import SynthesisOptions, SynthesisResult, VoiceRef, WordTiming
from motionile.engine.audio.providers.base import ProviderUnavailableError, TTSProvider
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.audio.synthesis import EmptyNarrationTextError, NewCacheEntry
from motionile.modules.credits import UsageEntry
from motionile.modules.media import AssetService
from motionile.modules.media import speech_cache as speech_cache_module
from motionile.modules.media.speech import SpeechService
from motionile.modules.media.speech_cache import SqlSynthesisCache

VOICE = VoiceRef("fake", "fake-voice-aria", "en")
OTHER_VOICE = VoiceRef("fake", "fake-voice-bram", "en")
OPTIONS = SynthesisOptions(language="en", output_format="wav")
TEXT = "Every video begins with a question."


@dataclass
class Harness:
    world: World
    storage: InMemoryStorage
    clock: FrozenClock
    provider: FakeTTSProvider
    cache: SqlSynthesisCache
    service: SpeechService
    usage: list[UsageEntry] = field(default_factory=list[UsageEntry])
    requested: list[str | None] = field(default_factory=list[str | None])


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    world = World()
    storage = InMemoryStorage()
    clock = FrozenClock(NOW)
    provider = FakeTTSProvider()
    assets = AssetService(storage, world.asset_store)
    cache = SqlSynthesisCache(world.transaction, assets, clock, world.tts_store)
    recorded: list[UsageEntry] = []
    requested: list[str | None] = []

    async def record_usage(session: object, entry: UsageEntry) -> None:
        del session
        recorded.append(entry)

    monkeypatch.setattr(speech_cache_module, "record_usage", record_usage)

    def providers(name: str | None) -> TTSProvider:
        requested.append(name)
        return provider

    service = SpeechService(world.transaction, cache, make_settings(), providers)
    return Harness(world, storage, clock, provider, cache, service, recorded, requested)


async def test_a_miss_synthesizes_stores_the_audio_and_records_usage(harness: Harness) -> None:
    result = await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    assert not result.cache_hit
    assert result.provider == "fake"
    assert result.characters == len(TEXT)
    assert result.duration_ms > 0
    assert [word.text for word in result.words] == TEXT.split()
    assert len(harness.provider.calls) == 1
    [entry] = harness.world.entries.values()
    assert entry.provider == "fake"
    assert entry.provider_voice_id == "fake-voice-aria"
    assert entry.hit_count == 0
    [asset] = harness.world.assets.values()
    assert asset.owner_user_id is None
    assert asset.kind == "audio"
    assert asset.storage_key == f"tts/{entry.content_hash.hex()[:2]}/{entry.content_hash.hex()}.wav"
    assert harness.storage.objects[asset.storage_key].data == result.audio
    [usage] = harness.usage
    assert (usage.user_id, usage.stage, usage.provider, usage.model) == (USER_A, "tts", "fake", "fake-tts-1")
    assert (usage.audio_characters, usage.cost_micros_usd, usage.credits) == (len(TEXT), 0, 0)
    assert usage.key.startswith("tts:")


async def test_the_entry_is_keyed_by_the_content_hash(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    [entry] = harness.world.entries.values()
    assert entry.content_hash == tts_cache_key("fake", "fake-tts-1", "fake-voice-aria", TEXT, OPTIONS)


async def test_a_hit_returns_the_same_audio_without_synthesizing_or_paying(harness: Harness) -> None:
    first = await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)
    harness.clock.advance(timedelta(hours=1))

    second = await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    assert second.cache_hit
    assert second.audio == first.audio
    assert second.words == first.words
    assert second.duration_ms == first.duration_ms
    assert len(harness.provider.calls) == 1
    assert len(harness.usage) == 1
    [entry] = harness.world.entries.values()
    assert entry.hit_count == 1
    assert entry.last_used_at == NOW + timedelta(hours=1)


async def test_whitespace_differences_hit_the_same_entry(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, "Hello   brave\nnew world", OPTIONS, user_id=USER_A)

    second = await harness.service.synthesize_text(VOICE, " Hello brave new world ", OPTIONS, user_id=USER_A)

    assert second.cache_hit
    assert len(harness.world.entries) == 1


async def test_another_voice_or_text_or_setting_is_a_separate_entry(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(OTHER_VOICE, TEXT, OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(VOICE, TEXT + " More.", OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(VOICE, TEXT, SynthesisOptions(language="en", speed=1.1), user_id=USER_A)

    assert len(harness.world.entries) == 4
    assert len(harness.usage) == 4


async def test_the_provider_is_chosen_from_the_voice(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    assert harness.requested == ["fake"]


async def test_a_failed_synthesis_stores_nothing_and_records_no_usage(harness: Harness) -> None:
    harness.provider.failure = ProviderUnavailableError("down")

    with pytest.raises(ProviderUnavailableError):
        await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    assert harness.world.entries == {}
    assert harness.world.assets == {}
    assert harness.usage == []


async def test_empty_text_is_refused_before_any_work(harness: Harness) -> None:
    with pytest.raises(EmptyNarrationTextError):
        await harness.service.synthesize_text(VOICE, "  \n ", OPTIONS, user_id=USER_A)

    assert harness.provider.calls == []


def scripted_result(duration_ms: int) -> SynthesisResult:
    return SynthesisResult(
        audio=b"RIFF" + bytes([duration_ms % 256]) * 40,
        content_type="audio/wav",
        duration_ms=duration_ms,
        words=(WordTiming("hello", 0, duration_ms),),
        characters=5,
        cost_micros_usd=0,
        model="fake-tts-1",
    )


async def test_the_loser_of_a_race_gets_the_winners_entry(harness: Harness) -> None:
    key = tts_cache_key("fake", "fake-tts-1", "fake-voice-aria", "hello", OPTIONS)

    winner = await harness.cache.put(NewCacheEntry(key, "fake", VOICE, scripted_result(900)))
    loser = await harness.cache.put(NewCacheEntry(key, "fake", VOICE, scripted_result(1100)))

    assert winner.duration_ms == 900
    assert loser.duration_ms == 900
    assert loser.audio == winner.audio
    assert len(harness.world.entries) == 1
    assert len(harness.world.assets) == 1


async def test_a_missing_audio_object_is_a_miss_and_is_replaced(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)
    [asset] = harness.world.assets.values()
    del harness.storage.objects[asset.storage_key]

    again = await harness.service.synthesize_text(VOICE, TEXT, OPTIONS, user_id=USER_A)

    assert not again.cache_hit
    assert len(harness.provider.calls) == 2
    assert len(harness.world.entries) == 1
    assert harness.storage.objects[asset.storage_key].data == again.audio


async def test_deleting_a_voices_cache_removes_entries_assets_and_objects(harness: Harness) -> None:
    for sentence in ("One.", "Two.", "Three."):
        await harness.service.synthesize_text(VOICE, sentence, OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(OTHER_VOICE, "Four.", OPTIONS, user_id=USER_A)

    deleted = await harness.service.delete_cache_for_voice("fake", "fake-voice-aria")

    assert deleted == 3
    [entry] = harness.world.entries.values()
    assert entry.provider_voice_id == "fake-voice-bram"
    assert len(harness.world.assets) == 1
    assert len(harness.storage.objects) == 1


async def test_deleting_the_cache_of_an_unused_voice_is_a_no_op(harness: Harness) -> None:
    assert await harness.service.delete_cache_for_voice("fake", "nobody") == 0


async def test_pruning_removes_only_entries_unused_since_the_cutoff(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, "Old.", OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(VOICE, "Used.", OPTIONS, user_id=USER_A)
    harness.clock.advance(timedelta(days=100))
    await harness.service.synthesize_text(VOICE, "Used.", OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(VOICE, "Fresh.", OPTIONS, user_id=USER_A)

    pruned = await harness.service.prune_cache(harness.clock.now() - timedelta(days=90))

    assert pruned == 1
    remaining = sorted(entry.characters for entry in harness.world.entries.values())
    assert remaining == sorted([len("Fresh."), len("Used.")])
    assert len(harness.storage.objects) == 2


async def test_pruning_walks_every_batch(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    for index in range(5):
        await harness.service.synthesize_text(VOICE, f"Sentence {index}.", OPTIONS, user_id=USER_A)
    harness.clock.advance(timedelta(days=200))
    monkeypatch.setattr(speech_cache_module, "EVICT_BATCH_SIZE", 2)

    pruned = await harness.service.prune_cache(harness.clock.now() - timedelta(days=90))

    assert pruned == 5
    assert harness.world.entries == {}
    assert harness.storage.objects == {}


def live_settings() -> Settings:
    return Settings(app=AppSettings(env=AppEnv.CI, providers_mode=ProvidersMode.LIVE))


def options_for(settings: Settings, provider: str) -> SynthesisOptions:
    world = World()
    cache = SqlSynthesisCache(world.transaction, AssetService(InMemoryStorage(), world.asset_store), FrozenClock(NOW))
    service = SpeechService(world.transaction, cache, settings, lambda _: FakeTTSProvider())
    return service.default_options(provider, "hi", speed=1.1, stability=0.4)


def test_default_options_follow_the_provider_and_mode() -> None:
    assert options_for(make_settings(), "fake").output_format == "wav"
    assert options_for(live_settings(), "elevenlabs").output_format == "mp3_44100_128"
    assert options_for(live_settings(), "openai").output_format == "mp3"
    carried = options_for(live_settings(), "elevenlabs")
    assert (carried.language, carried.speed, carried.stability) == ("hi", 1.1, 0.4)


async def test_usage_keys_are_unique_per_synthesis(harness: Harness) -> None:
    await harness.service.synthesize_text(VOICE, "One.", OPTIONS, user_id=USER_A)
    await harness.service.synthesize_text(VOICE, "Two.", OPTIONS, user_id=USER_A)

    assert len({entry.key for entry in harness.usage}) == 2
