import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from motionile.core.http.safe_client import SafeHttpClient
from motionile.engine.audio.models import SynthesisOptions, SynthesisResult, Transcript, VoiceRef, WordTiming
from motionile.engine.audio.providers.aligner import Aligner
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
from motionile.engine.audio.timing import seconds_to_ms

PROVIDER_NAME = "openai"
MAX_INPUT_CHARACTERS = 4096
MIN_SPEED = 0.25
MAX_SPEED = 4.0
CHARACTERS_PER_PRICE_UNIT = 1000
SPEED_UNSUPPORTED_PREFIX = "gpt-4o"
CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "opus": "audio/ogg",
}
EXTENSIONS = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/flac": "flac", "audio/aac": "aac", "audio/ogg": "ogg"}


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    api_key: SecretStr
    base_url: str = "https://api.openai.com"
    tts_model: str = "gpt-4o-mini-tts"
    transcribe_model: str = "whisper-1"
    cost_micros_per_1k_chars: int = 15_000


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SpokenWord(ResponseModel):
    word: str
    start: float
    end: float


class VerboseTranscription(ResponseModel):
    text: str = ""
    words: list[SpokenWord] = Field(default_factory=list[SpokenWord])


def content_type_for(output_format: str) -> str:
    content_type = CONTENT_TYPES.get(output_format)
    if content_type is None:
        raise ProviderRejectedError("the output format is not supported", reason="unsupported_output_format")
    return content_type


def price_for(characters: int, cost_micros_per_1k_chars: int) -> int:
    return -(-characters * cost_micros_per_1k_chars // CHARACTERS_PER_PRICE_UNIT)


def parse_transcription(payload: object) -> Transcript:
    try:
        transcription = VerboseTranscription.model_validate(payload)
    except ValidationError:
        raise ProviderResponseError("the transcription payload has an unexpected shape") from None
    words = tuple(
        WordTiming(word.word.strip(), seconds_to_ms(word.start), seconds_to_ms(word.end))
        for word in transcription.words
        if word.word.strip()
    )
    return Transcript(text=transcription.text, words=words)


class OpenAIApi:
    def __init__(
        self,
        http: SafeHttpClient,
        config: OpenAIConfig,
        *,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.config = config
        endpoint = ProviderEndpoint(
            PROVIDER_NAME, config.base_url, {"Authorization": f"Bearer {config.api_key.get_secret_value()}"}
        )
        self.http = ProviderHttp(http, endpoint, sleep=sleep, retry=retry)

    def __repr__(self) -> str:
        return f"OpenAIApi(base_url={self.config.base_url!r})"


class OpenAITranscriber:
    name = PROVIDER_NAME

    def __init__(self, api: OpenAIApi) -> None:
        self._api = api

    async def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript:
        fields = [
            ("model", self._api.config.transcribe_model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
        ]
        code = iso639_1(language)
        if code is not None:
            fields.append(("language", code))
        body = encode_multipart(fields, [MultipartFile("file", filename, audio, "application/octet-stream")])
        request = ApiRequest("POST", "/v1/audio/transcriptions", replayable=False, multipart=body)
        return parse_transcription(await self._api.http.send_json(request))


class OpenAITTS:
    name = PROVIDER_NAME
    returns_native_timestamps = False

    def __init__(self, api: OpenAIApi, meter: AudioDurationMeter, aligner: Aligner) -> None:
        self._api = api
        self._meter = meter
        self._aligner = aligner
        self.model = api.config.tts_model

    def request_body(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> dict[str, object]:
        model = self._api.config.tts_model
        body: dict[str, object] = {
            "model": model,
            "input": text,
            "voice": safe_identifier(voice.provider_voice_id),
            "response_format": options.output_format,
        }
        if not model.startswith(SPEED_UNSUPPORTED_PREFIX):
            body["speed"] = min(max(options.speed, MIN_SPEED), MAX_SPEED)
        return body

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult:
        content_type = content_type_for(options.output_format)
        if len(text) > MAX_INPUT_CHARACTERS:
            raise ProviderRejectedError("the text is too long for one request", reason="text_too_long")
        request = ApiRequest(
            "POST",
            "/v1/audio/speech",
            replayable=False,
            json_body=self.request_body(text, voice, options),
            accept=content_type,
        )
        audio = (await self._api.http.send(request)).content
        if not audio:
            raise ProviderResponseError("the response has no audio")
        duration_ms = await self._meter.measure_ms(audio)
        words = await self._aligner.align(
            audio,
            text,
            voice.language or options.language,
            filename=f"speech.{EXTENSIONS[content_type]}",
            duration_ms=duration_ms,
        )
        characters = len(text)
        return SynthesisResult(
            audio=audio,
            content_type=content_type,
            duration_ms=duration_ms,
            words=words,
            characters=characters,
            cost_micros_usd=price_for(characters, self._api.config.cost_micros_per_1k_chars),
            model=self._api.config.tts_model,
        )
