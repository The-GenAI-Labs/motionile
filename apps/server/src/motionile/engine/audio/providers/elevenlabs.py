import asyncio
import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from motionile.core.http.safe_client import SafeHttpClient
from motionile.engine.audio.models import (
    CloneSample,
    ProviderVoice,
    SynthesisOptions,
    SynthesisResult,
    Transcript,
    VoiceRef,
    WordTiming,
)
from motionile.engine.audio.providers.base import (
    AudioDurationMeter,
    ProviderRejectedError,
    ProviderResponseError,
)
from motionile.engine.audio.providers.transport import (
    ApiRequest,
    MultipartFile,
    ProviderEndpoint,
    ProviderHttp,
    RetryPolicy,
    Sleep,
    encode_multipart,
    iso639_1,
    safe_identifier,
)
from motionile.engine.audio.timing import clamp_words, seconds_to_ms

PROVIDER_NAME = "elevenlabs"
MIN_SPEED = 0.7
MAX_SPEED = 1.2
CHARACTERS_PER_PRICE_UNIT = 1000
CONTENT_TYPES = {"mp3": "audio/mpeg", "opus": "audio/ogg"}
LANGUAGE_CODE_MODELS = frozenset({"eleven_turbo_v2_5", "eleven_flash_v2_5", "eleven_v3"})
MAX_CLONE_SAMPLES = 25


@dataclass(frozen=True, slots=True)
class ElevenLabsConfig:
    api_key: SecretStr
    base_url: str = "https://api.elevenlabs.io"
    tts_model: str = "eleven_multilingual_v2"
    stt_model: str = "scribe_v1"
    cost_micros_per_1k_chars: int = 180_000
    similarity_boost: float = 0.75
    language_code_models: frozenset[str] = field(default=LANGUAGE_CODE_MODELS)


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Alignment(ResponseModel):
    characters: list[str]
    character_start_times_seconds: list[float]
    character_end_times_seconds: list[float]


class TimestampedSpeech(ResponseModel):
    audio_base64: str
    alignment: Alignment | None = None


class SpeechWord(ResponseModel):
    text: str
    type: str = "word"
    start: float | None = None
    end: float | None = None


class SpeechTranscript(ResponseModel):
    text: str = ""
    words: list[SpeechWord] = Field(default_factory=list[SpeechWord])


class VerifiedLanguage(ResponseModel):
    language: str | None = None


class VoiceEntry(ResponseModel):
    voice_id: str
    name: str
    labels: dict[str, str | None] = Field(default_factory=dict[str, str | None])
    preview_url: str | None = None
    verified_languages: list[VerifiedLanguage] | None = None


class VoiceList(ResponseModel):
    voices: list[VoiceEntry]


class AddedVoice(ResponseModel):
    voice_id: str


def content_type_for(output_format: str) -> str:
    family = output_format.split("_", maxsplit=1)[0]
    content_type = CONTENT_TYPES.get(family)
    if content_type is None:
        raise ProviderRejectedError("the output format has no container", reason="unsupported_output_format")
    return content_type


def price_for(characters: int, cost_micros_per_1k_chars: int) -> int:
    return -(-characters * cost_micros_per_1k_chars // CHARACTERS_PER_PRICE_UNIT)


def word_from(pieces: Sequence[str], alignment: Alignment, first: int, last: int) -> WordTiming:
    return WordTiming(
        "".join(pieces),
        seconds_to_ms(alignment.character_start_times_seconds[first]),
        seconds_to_ms(alignment.character_end_times_seconds[last]),
    )


def words_from_alignment(alignment: Alignment) -> tuple[WordTiming, ...]:
    count = len(alignment.characters)
    if len(alignment.character_start_times_seconds) != count or len(alignment.character_end_times_seconds) != count:
        raise ProviderResponseError("the alignment arrays differ in length")
    words: list[WordTiming] = []
    pieces: list[str] = []
    first = 0
    for index, character in enumerate(alignment.characters):
        if character.strip():
            if not pieces:
                first = index
            pieces.append(character)
        elif pieces:
            words.append(word_from(pieces, alignment, first, index - 1))
            pieces = []
    if pieces:
        words.append(word_from(pieces, alignment, first, count - 1))
    return tuple(words)


def words_from_speech(words: Sequence[SpeechWord]) -> tuple[WordTiming, ...]:
    timings: list[WordTiming] = []
    for word in words:
        text = word.text.strip()
        if word.type != "word" or not text or word.start is None or word.end is None:
            continue
        timings.append(WordTiming(text, seconds_to_ms(word.start), seconds_to_ms(word.end)))
    return tuple(timings)


def voice_from(entry: VoiceEntry) -> ProviderVoice:
    labels = {key: value for key, value in entry.labels.items() if isinstance(value, str)}
    language = labels.get("language")
    if language is None and entry.verified_languages:
        language = entry.verified_languages[0].language
    return ProviderVoice(
        provider_voice_id=entry.voice_id,
        name=entry.name,
        language=language,
        labels=labels,
        preview_url=entry.preview_url,
    )


def parse[ModelT: ResponseModel](model: type[ModelT], payload: object) -> ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise ProviderResponseError(f"the {model.__name__} payload has an unexpected shape") from None


class ElevenLabsApi:
    def __init__(
        self,
        http: SafeHttpClient,
        config: ElevenLabsConfig,
        *,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.config = config
        endpoint = ProviderEndpoint(PROVIDER_NAME, config.base_url, {"xi-api-key": config.api_key.get_secret_value()})
        self.http = ProviderHttp(http, endpoint, sleep=sleep, retry=retry)

    def __repr__(self) -> str:
        return f"ElevenLabsApi(base_url={self.config.base_url!r})"


class ElevenLabsTTS:
    name = PROVIDER_NAME
    returns_native_timestamps = True

    def __init__(self, api: ElevenLabsApi, meter: AudioDurationMeter) -> None:
        self._api = api
        self._meter = meter
        self.model = api.config.tts_model

    def request_body(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> dict[str, object]:
        config = self._api.config
        body: dict[str, object] = {
            "text": text,
            "model_id": config.tts_model,
            "voice_settings": {
                "stability": min(max(options.stability, 0.0), 1.0),
                "similarity_boost": config.similarity_boost,
                "speed": min(max(options.speed, MIN_SPEED), MAX_SPEED),
            },
        }
        language = iso639_1(voice.language or options.language)
        if language is not None and config.tts_model in config.language_code_models:
            body["language_code"] = language
        return body

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult:
        content_type = content_type_for(options.output_format)
        request = ApiRequest(
            "POST",
            f"/v1/text-to-speech/{safe_identifier(voice.provider_voice_id)}/with-timestamps",
            replayable=False,
            query={"output_format": options.output_format},
            json_body=self.request_body(text, voice, options),
        )
        speech = parse(TimestampedSpeech, await self._api.http.send_json(request))
        if speech.alignment is None:
            raise ProviderResponseError("the response has no alignment")
        try:
            audio = base64.b64decode(speech.audio_base64, validate=True)
        except (binascii.Error, ValueError):
            raise ProviderResponseError("the audio is not valid base64") from None
        if not audio:
            raise ProviderResponseError("the response has no audio")
        duration_ms = await self._meter.measure_ms(audio)
        characters = len(text)
        return SynthesisResult(
            audio=audio,
            content_type=content_type,
            duration_ms=duration_ms,
            words=clamp_words(words_from_alignment(speech.alignment), duration_ms),
            characters=characters,
            cost_micros_usd=price_for(characters, self._api.config.cost_micros_per_1k_chars),
            model=self._api.config.tts_model,
        )


class ElevenLabsTranscriber:
    name = PROVIDER_NAME

    def __init__(self, api: ElevenLabsApi) -> None:
        self._api = api

    async def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        fields = [
            ("model_id", self._api.config.stt_model),
            ("timestamps_granularity", "word"),
            ("tag_audio_events", "false"),
            ("diarize", "false"),
        ]
        code = iso639_1(language)
        if code is not None:
            fields.append(("language_code", code))
        body = encode_multipart(fields, [MultipartFile("file", filename, audio, "application/octet-stream")])
        request = ApiRequest("POST", "/v1/speech-to-text", replayable=False, multipart=body)
        transcript = parse(SpeechTranscript, await self._api.http.send_json(request))
        return Transcript(text=transcript.text, words=words_from_speech(transcript.words))


class ElevenLabsVoices:
    def __init__(self, api: ElevenLabsApi) -> None:
        self._api = api

    async def list_voices(self) -> Sequence[ProviderVoice]:
        payload = await self._api.http.send_json(ApiRequest("GET", "/v1/voices", replayable=True))
        return [voice_from(entry) for entry in parse(VoiceList, payload).voices]

    async def clone(
        self, name: str, language: str | None, samples: Sequence[CloneSample], description: str | None
    ) -> str:
        if not samples or len(samples) > MAX_CLONE_SAMPLES:
            raise ProviderRejectedError("the number of samples is out of range", reason="invalid_samples")
        fields = [("name", name), ("remove_background_noise", "false")]
        if description:
            fields.append(("description", description))
        if language:
            fields.append(("labels", json.dumps({"language": language})))
        files = [MultipartFile("files", sample.filename, sample.content, sample.content_type) for sample in samples]
        request = ApiRequest("POST", "/v1/voices/add", replayable=False, multipart=encode_multipart(fields, files))
        return safe_identifier(parse(AddedVoice, await self._api.http.send_json(request)).voice_id)

    async def delete(self, provider_voice_id: str) -> None:
        path = f"/v1/voices/{safe_identifier(provider_voice_id)}"
        await self._api.http.send(ApiRequest("DELETE", path, replayable=True))
