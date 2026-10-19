from motionile.engine.audio.providers.base import ProviderResponseError
from motionile.engine.audio.sources import ALLOWED_DEMUXERS, staged_source
from motionile.engine.ffmpeg import FfmpegError, FfmpegTools, run_ffmpeg

MEASURE_SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 2
MS_PER_SECOND = 1000
MEASURE_TIMEOUT_SECONDS = 60.0
MEASURE_ARGUMENTS = (
    "-vn",
    "-map",
    "0:a:0",
    "-ac",
    "1",
    "-ar",
    str(MEASURE_SAMPLE_RATE),
    "-f",
    "s16le",
    "pipe:1",
)


class FfmpegDurationMeter:
    def __init__(self, tools: FfmpegTools) -> None:
        self._tools = tools

    async def measure_ms(self, audio: bytes) -> int:
        try:
            async with staged_source(audio, formats=ALLOWED_DEMUXERS) as source:
                result = await run_ffmpeg(
                    self._tools,
                    [*source.arguments, *MEASURE_ARGUMENTS],
                    timeout_seconds=MEASURE_TIMEOUT_SECONDS,
                    stdin=source.stdin,
                )
        except FfmpegError:
            raise ProviderResponseError("the generated audio could not be decoded") from None
        duration = len(result.stdout) * MS_PER_SECOND // (MEASURE_SAMPLE_RATE * BYTES_PER_SAMPLE)
        if duration <= 0:
            raise ProviderResponseError("the generated audio has no measurable duration")
        return duration
