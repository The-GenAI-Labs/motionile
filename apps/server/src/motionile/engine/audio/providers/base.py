from collections.abc import Sequence
from typing import ClassVar, Protocol

from motionile.engine.audio.models import (
    CloneSample,
    ProviderVoice,
    SynthesisOptions,
    SynthesisResult,
    Transcript,
    VoiceRef,
)


class ProviderError(Exception):
    code: ClassVar[str] = "provider_error"
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, status_code: int | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reason = reason


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    retryable = True


class ProviderRateLimitedError(ProviderError):
    code = "provider_rate_limited"
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, reason=reason)
        self.retry_after_seconds = retry_after_seconds


class ProviderRejectedError(ProviderError):
    code = "provider_rejected"


class ProviderAuthenticationError(ProviderError):
    code = "provider_authentication_failed"


class ProviderNotFoundError(ProviderError):
    code = "provider_not_found"


class ProviderResponseError(ProviderError):
    code = "provider_invalid_response"


class ProviderConfigurationError(ProviderError):
    code = "provider_misconfigured"


class AudioDurationMeter(Protocol):
    async def measure_ms(self, audio: bytes) -> int: ...


class TTSProvider(Protocol):
    name: str
    model: str
    returns_native_timestamps: bool

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult: ...


class Transcriber(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str, language: str | None) -> Transcript: ...


class VoiceCatalog(Protocol):
    async def list_voices(self) -> Sequence[ProviderVoice]: ...


class VoiceCloner(Protocol):
    async def clone(
        self, name: str, language: str | None, samples: Sequence[CloneSample], description: str | None
    ) -> str: ...

    async def delete(self, provider_voice_id: str) -> None: ...
