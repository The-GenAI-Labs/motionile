import pytest
from tests.integration.engine.audio.support import MediaFactory

from motionile.engine.audio.providers.base import ProviderResponseError
from motionile.engine.audio.providers.measure import FfmpegDurationMeter
from motionile.engine.ffmpeg import FfmpegTools

pytestmark = pytest.mark.slow


@pytest.mark.parametrize(
    ("name", "output_arguments"),
    [("tone.mp3", ("-c:a", "libmp3lame", "-b:a", "128k")), ("tone.wav", ()), ("tone.opus", ("-c:a", "libopus"))],
)
async def test_duration_is_measured_from_the_audio(
    tools: FfmpegTools, media: MediaFactory, name: str, output_arguments: tuple[str, ...]
) -> None:
    audio = (await media.make(name, "sine=frequency=330:duration=4", *output_arguments)).read_bytes()

    duration = await FfmpegDurationMeter(tools).measure_ms(audio)

    assert 3900 <= duration <= 4150


async def test_unreadable_audio_is_a_provider_response_error(tools: FfmpegTools) -> None:
    with pytest.raises(ProviderResponseError):
        await FfmpegDurationMeter(tools).measure_ms(b"definitely not audio" * 50)
