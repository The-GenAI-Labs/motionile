import hashlib
import struct
import unicodedata

from motionile.engine.audio.models import SynthesisOptions

CACHE_KEY_VERSION = "tts-cache-v1"
LENGTH_PREFIX = struct.Struct(">Q")


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def canonical_decimal(value: float) -> str:
    return f"{value:.4f}"


def canonical_settings(options: SynthesisOptions) -> tuple[str, str, str, str]:
    return (
        canonical_decimal(options.speed),
        canonical_decimal(options.stability),
        options.language.strip().lower(),
        options.output_format.strip().lower(),
    )


def tts_cache_key(provider: str, model: str, provider_voice_id: str, text: str, settings: SynthesisOptions) -> bytes:
    fields = (
        CACHE_KEY_VERSION,
        provider,
        model,
        provider_voice_id,
        normalize_text(text),
        *canonical_settings(settings),
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(LENGTH_PREFIX.pack(len(encoded)))
        digest.update(encoded)
    return digest.digest()
