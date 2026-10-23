from pathlib import Path
from uuid import UUID

from motionile.engine.audio.models import VoiceRef
from motionile.engine.audio.narration import NormalizedAudio, SceneAudio, normalize_scene_audio
from motionile.engine.audio.providers.aligner import Aligner
from motionile.engine.audio.providers.base import Transcriber
from motionile.engine.audio.providers.measure import FfmpegDurationMeter
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.media.pipeline.ports import AudioNormalizer, SpeechPort
from motionile.modules.media.render_options import ResolvedVoice


def voice_ref(voice: ResolvedVoice) -> VoiceRef:
    return VoiceRef(provider=voice.provider, provider_voice_id=voice.provider_voice_id, language=voice.language)


class FfmpegNormalizer:
    def __init__(self, tools: FfmpegTools) -> None:
        self._tools = tools

    async def normalize(self, source: bytes, destination: Path) -> NormalizedAudio:
        return await normalize_scene_audio(self._tools, source, destination)


class SceneNarrator:
    def __init__(
        self, speech: SpeechPort, normalizer: AudioNormalizer, transcriber: Transcriber, tools: FfmpegTools
    ) -> None:
        self._speech = speech
        self._normalizer = normalizer
        self._transcriber = transcriber
        self._tools = tools

    async def synthesized(
        self, user_id: UUID, voice: ResolvedVoice, scene_id: str, text: str, destination: Path
    ) -> SceneAudio:
        options = self._speech.default_options(voice.provider, voice.language)
        spoken = await self._speech.synthesize_text(voice_ref(voice), text, options, user_id=user_id)
        normalized = await self._normalizer.normalize(spoken.audio, destination)
        return SceneAudio(scene_id, text, normalized.duration_ms, spoken.words, normalized.path)

    async def uploaded(
        self, scene_id: str, text: str | None, source: bytes, filename: str, destination: Path
    ) -> SceneAudio:
        normalized = await self._normalizer.normalize(source, destination)
        if text:
            aligner = Aligner(self._transcriber, FfmpegDurationMeter(self._tools))
            words = await aligner.align(source, text, None, filename=filename, duration_ms=normalized.duration_ms)
            return SceneAudio(scene_id, text, normalized.duration_ms, words, normalized.path)
        transcript = await self._transcriber.transcribe(source, filename, None)
        return SceneAudio(scene_id, transcript.text, normalized.duration_ms, transcript.words, normalized.path)
