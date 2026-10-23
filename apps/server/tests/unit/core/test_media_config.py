import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from pydantic import SecretStr, ValidationError
from tests.fakes.settings import STRONG_SECRET
from tests.fakes.settings import deployed_settings as deployed

from motionile.core.config import (
    AppEnv,
    AppSettings,
    AudioSettings,
    AuthSettings,
    ElevenLabsSettings,
    MediaDeliveryMode,
    MediaSettings,
    OpenAISettings,
    RenderSettings,
    Settings,
    VoicesSettings,
    parse_private_key_pem,
)

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_PEM = RSA_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
LEGACY_RSA_PEM = RSA_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
).decode()
EC_PEM = (
    ec.generate_private_key(ec.SECP256R1())
    .private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    .decode()
)
ENCRYPTED_PEM = RSA_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"passphrase")
).decode()
CLOUDFRONT_ENVIRONMENT = {
    "MEDIA_DELIVERY_MODE": "cloudfront",
    "CDN_DOMAIN": "cdn.motionile.com",
    "CLOUDFRONT_KEY_PAIR_ID": "K2JCJMDEHXQW5F",
    "CLOUDFRONT_PRIVATE_KEY": RSA_PEM,
}


def cloudfront_settings(**overrides: object) -> Settings:
    complete = deployed()
    media = MediaSettings.model_validate(
        {
            "delivery_mode": MediaDeliveryMode.CLOUDFRONT,
            "cdn_domain": "cdn.motionile.com",
            "cloudfront_key_pair_id": "K2JCJMDEHXQW5F",
            "cloudfront_private_key": SecretStr(RSA_PEM),
            **overrides,
        }
    )
    return complete.model_copy(update={"media": media})


def test_render_defaults_match_the_reference() -> None:
    render = RenderSettings()

    assert render.fps == 30
    assert render.x264_crf == 20
    assert render.x264_preset == "veryfast"
    assert render.parallel_pages is None
    assert render.chunk_seconds == 5
    assert render.scene_padding_ms == 400
    assert render.tail_ms == 1_000
    assert render.max_duration_ms == 120_000
    assert render.poster_ms == 2_000
    assert render.page_load_timeout_seconds == 15
    assert render.ready_timeout_seconds == 15
    assert render.frame_timeout_seconds == 10
    assert render.stage_timeout_seconds == 1_800
    assert render.stall_seconds == 900
    assert render.min_free_disk_mb == 2_048
    assert render.browser_memory_mb == 768
    assert render.work_directory is None
    assert render.golden_directory is None
    assert render.ffmpeg_path == "ffmpeg"
    assert render.ffprobe_path == "ffprobe"


def test_render_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RENDER_FPS", "24")
    monkeypatch.setenv("RENDER_X264_CRF", "18")
    monkeypatch.setenv("RENDER_X264_PRESET", "medium")
    monkeypatch.setenv("RENDER_PARALLEL_PAGES", "3")
    monkeypatch.setenv("RENDER_WORK_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("RENDER_GOLDEN_DIRECTORY", str(tmp_path / "golden"))
    monkeypatch.setenv("RENDER_FFMPEG_PATH", "/opt/ffmpeg/bin/ffmpeg")
    monkeypatch.setenv("RENDER_MAX_DURATION_MS", "60000")

    render = Settings().render

    assert render.fps == 24
    assert render.x264_crf == 18
    assert render.x264_preset == "medium"
    assert render.parallel_pages == 3
    assert render.work_directory == tmp_path
    assert render.golden_directory == tmp_path / "golden"
    assert render.ffmpeg_path == "/opt/ffmpeg/bin/ffmpeg"
    assert render.max_duration_ms == 60_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fps", 23),
        ("fps", 61),
        ("x264_crf", -1),
        ("x264_crf", 52),
        ("x264_preset", "turbo"),
        ("parallel_pages", 0),
        ("parallel_pages", 9),
        ("chunk_seconds", 0),
        ("chunk_seconds", 31),
        ("scene_padding_ms", -1),
        ("scene_padding_ms", 2_001),
        ("tail_ms", -1),
        ("tail_ms", 5_001),
        ("max_duration_ms", 120_001),
        ("max_duration_ms", 999),
        ("poster_ms", -1),
        ("page_load_timeout_seconds", 0),
        ("ready_timeout_seconds", 301),
        ("frame_timeout_seconds", 0),
        ("stage_timeout_seconds", 59),
        ("stall_seconds", 59),
        ("min_free_disk_mb", -1),
        ("browser_memory_mb", 127),
        ("ffmpeg_path", ""),
        ("ffprobe_path", ""),
    ],
)
def test_render_settings_are_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RenderSettings.model_validate({field: value})


@pytest.mark.parametrize("preset", ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
def test_render_accepts_every_x264_preset(preset: str) -> None:
    assert RenderSettings.model_validate({"x264_preset": preset}).x264_preset == preset


@pytest.mark.parametrize("preset", ["ultrafast", "superfast", "placebo"])
def test_render_rejects_presets_that_break_the_high_profile(preset: str) -> None:
    with pytest.raises(ValidationError):
        RenderSettings.model_validate({"x264_preset": preset})


def test_render_blank_values_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RENDER_FPS",
        "RENDER_PARALLEL_PAGES",
        "RENDER_WORK_DIRECTORY",
        "RENDER_GOLDEN_DIRECTORY",
        "RENDER_FFMPEG_PATH",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("RENDER_STALL_SECONDS", "")

    render = Settings().render

    assert render.fps == 30
    assert render.parallel_pages is None
    assert render.work_directory is None
    assert render.golden_directory is None
    assert render.ffmpeg_path == "ffmpeg"
    assert render.stall_seconds == 900


def test_render_whitespace_values_are_treated_as_unset_for_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_PARALLEL_PAGES", "  ")
    monkeypatch.setenv("RENDER_WORK_DIRECTORY", "  ")

    render = Settings().render

    assert render.parallel_pages is None
    assert render.work_directory is None


def test_parallel_pages_follow_the_cpu_count_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()

    monkeypatch.setattr("motionile.core.config.os.cpu_count", lambda: 4)
    assert settings.parallel_render_pages == 4
    monkeypatch.setattr("motionile.core.config.os.cpu_count", lambda: 64)
    assert settings.parallel_render_pages == 8
    monkeypatch.setattr("motionile.core.config.os.cpu_count", lambda: None)
    assert settings.parallel_render_pages == 1


def test_explicit_parallel_pages_win_over_the_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("motionile.core.config.os.cpu_count", lambda: 16)

    settings = Settings(render=RenderSettings(parallel_pages=2))

    assert settings.parallel_render_pages == 2


def test_audio_defaults_and_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AudioSettings().tts_provider == "elevenlabs"
    assert AudioSettings().transcriber == "elevenlabs"

    monkeypatch.setenv("AUDIO_TTS_PROVIDER", "openai")
    monkeypatch.setenv("AUDIO_TRANSCRIBER", "openai")

    audio = Settings().audio

    assert audio.tts_provider == "openai"
    assert audio.transcriber == "openai"
    assert audio.providers == {"openai"}


@pytest.mark.parametrize("field", ["tts_provider", "transcriber"])
@pytest.mark.parametrize("value", ["fake", "google", "ElevenLabs"])
def test_audio_rejects_unknown_providers(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        AudioSettings.model_validate({field: value})


def test_elevenlabs_defaults() -> None:
    elevenlabs = ElevenLabsSettings()

    assert elevenlabs.api_key is None
    assert elevenlabs.api_base_url == "https://api.elevenlabs.io"
    assert elevenlabs.tts_model == "eleven_multilingual_v2"
    assert elevenlabs.stt_model == "scribe_v1"
    assert elevenlabs.output_format == "mp3_44100_128"
    assert elevenlabs.cost_micros_per_1k_chars == 180_000


def test_openai_defaults() -> None:
    openai = OpenAISettings()

    assert openai.api_key is None
    assert openai.api_base_url == "https://api.openai.com"
    assert openai.tts_model == "gpt-4o-mini-tts"
    assert openai.transcribe_model == "whisper-1"
    assert openai.cost_micros_per_1k_chars == 15_000


def test_provider_settings_read_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-key")
    monkeypatch.setenv("ELEVENLABS_API_BASE_URL", "https://eu.api.elevenlabs.io/")
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")
    monkeypatch.setenv("ELEVENLABS_STT_MODEL", "scribe_v2")
    monkeypatch.setenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_192")
    monkeypatch.setenv("ELEVENLABS_COST_MICROS_PER_1K_CHARS", "100000")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_API_BASE_URL", "https://api.openai.com")
    monkeypatch.setenv("OPENAI_TTS_MODEL", "tts-1")
    monkeypatch.setenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
    monkeypatch.setenv("OPENAI_COST_MICROS_PER_1K_CHARS", "20000")

    settings = Settings()

    assert settings.elevenlabs.api_key == SecretStr("eleven-key")
    assert settings.elevenlabs.api_base_url == "https://eu.api.elevenlabs.io"
    assert settings.elevenlabs.tts_model == "eleven_flash_v2_5"
    assert settings.elevenlabs.stt_model == "scribe_v2"
    assert settings.elevenlabs.output_format == "mp3_44100_192"
    assert settings.elevenlabs.cost_micros_per_1k_chars == 100_000
    assert settings.openai.api_key == SecretStr("openai-key")
    assert settings.openai.tts_model == "tts-1"
    assert settings.openai.transcribe_model == "gpt-4o-transcribe"
    assert settings.openai.cost_micros_per_1k_chars == 20_000


def test_provider_blank_keys_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ELEVENLABS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "  ")

    settings = Settings()

    assert settings.elevenlabs.api_key is None
    assert settings.openai.api_key is None


def test_provider_keys_are_not_rendered() -> None:
    settings = Settings(
        elevenlabs=ElevenLabsSettings(api_key=SecretStr("eleven-secret-value")),
        openai=OpenAISettings(api_key=SecretStr("openai-secret-value")),
    )

    rendered = repr(settings) + str(settings.model_dump())

    assert "eleven-secret-value" not in rendered
    assert "openai-secret-value" not in rendered


@pytest.mark.parametrize(
    "url",
    [
        "http://api.elevenlabs.io",
        "https://user:pass@api.elevenlabs.io",
        "https://api.elevenlabs.io/v1",
        "https://api.elevenlabs.io?x=1",
        "api.elevenlabs.io",
    ],
)
def test_provider_base_urls_must_be_plain_https_origins(url: str) -> None:
    with pytest.raises(ValidationError):
        ElevenLabsSettings(api_base_url=url)
    with pytest.raises(ValidationError):
        OpenAISettings(api_base_url=url)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_micros_per_1k_chars", -1),
        ("tts_model", ""),
        ("output_format", "MP3 44100"),
        ("output_format", ""),
    ],
)
def test_elevenlabs_values_are_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ElevenLabsSettings.model_validate({field: value})


@pytest.mark.parametrize(("field", "value"), [("cost_micros_per_1k_chars", -1), ("transcribe_model", "")])
def test_openai_values_are_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        OpenAISettings.model_validate({field: value})


def test_media_defaults_are_safe_for_local_development() -> None:
    media = MediaSettings()

    assert media.delivery_mode is MediaDeliveryMode.PRESIGNED
    assert media.cdn_domain is None
    assert media.cloudfront_key_pair_id is None
    assert media.cloudfront_private_key is None
    assert media.cookie_domain is None
    assert media.cookie_ttl_seconds == 3_600
    assert media.signed_url_ttl_seconds == 900
    assert media.private_key_pem is None


def test_media_reads_its_unprefixed_names_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in CLOUDFRONT_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MEDIA_COOKIE_DOMAIN", ".motionile.com")
    monkeypatch.setenv("MEDIA_COOKIE_TTL_SECONDS", "3000")
    monkeypatch.setenv("MEDIA_SIGNED_URL_TTL_SECONDS", "1800")

    media = Settings().media

    assert media.delivery_mode is MediaDeliveryMode.CLOUDFRONT
    assert media.cdn_domain == "cdn.motionile.com"
    assert media.cloudfront_key_pair_id == "K2JCJMDEHXQW5F"
    assert media.cloudfront_private_key is not None
    assert media.cookie_domain == ".motionile.com"
    assert media.cookie_ttl_seconds == 3_000
    assert media.signed_url_ttl_seconds == 1_800
    assert media.private_key_pem is not None


def test_media_can_be_built_by_field_name() -> None:
    media = MediaSettings(delivery_mode=MediaDeliveryMode.CLOUDFRONT, cdn_domain="CDN.Motionile.com")

    assert media.delivery_mode is MediaDeliveryMode.CLOUDFRONT
    assert media.cdn_domain == "cdn.motionile.com"


def test_media_blank_values_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MEDIA_DELIVERY_MODE",
        "CDN_DOMAIN",
        "CLOUDFRONT_KEY_PAIR_ID",
        "CLOUDFRONT_PRIVATE_KEY",
        "MEDIA_COOKIE_DOMAIN",
        "MEDIA_COOKIE_TTL_SECONDS",
        "MEDIA_SIGNED_URL_TTL_SECONDS",
    ):
        monkeypatch.setenv(name, "")

    settings = Settings()

    assert settings.media.delivery_mode is MediaDeliveryMode.PRESIGNED
    assert "delivery_mode" not in settings.media.model_fields_set
    assert settings.media.cdn_domain is None
    assert settings.media.cloudfront_key_pair_id is None
    assert settings.media.cloudfront_private_key is None
    assert settings.media.cookie_domain is None
    assert settings.media.cookie_ttl_seconds == 3_600


def test_media_whitespace_values_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CDN_DOMAIN", "CLOUDFRONT_KEY_PAIR_ID", "CLOUDFRONT_PRIVATE_KEY", "MEDIA_COOKIE_DOMAIN"):
        monkeypatch.setenv(name, "  ")

    media = Settings().media

    assert media.cdn_domain is None
    assert media.cloudfront_key_pair_id is None
    assert media.cloudfront_private_key is None
    assert media.cookie_domain is None


def test_media_cookie_domain_falls_back_to_the_auth_cookie_domain() -> None:
    assert Settings().media_cookie_domain is None
    assert Settings(auth=AuthSettings(cookie_domain=".motionile.com")).media_cookie_domain == ".motionile.com"
    explicit = Settings(
        auth=AuthSettings(cookie_domain=".motionile.com"), media=MediaSettings(cookie_domain=".media.motionile.com")
    )
    assert explicit.media_cookie_domain == ".media.motionile.com"


@pytest.mark.parametrize("mode", ["cdn", "CloudFront ", "signed", "none"])
def test_media_rejects_unknown_delivery_modes(mode: str) -> None:
    with pytest.raises(ValidationError):
        MediaSettings.model_validate({"delivery_mode": mode})


@pytest.mark.parametrize(
    "domain",
    [
        "https://cdn.motionile.com",
        "cdn.motionile.com/media",
        "cdn.motionile.com:443",
        "cdn.motionile.com/",
        "-cdn.motionile.com",
        "cdn..motionile.com",
        "cdn motionile.com",
        "user@cdn.motionile.com",
        "cdn.motionile.com?x=1",
        "a" * 64 + ".com",
    ],
)
def test_cdn_domain_must_be_a_bare_host_name(domain: str) -> None:
    with pytest.raises(ValidationError, match="bare host name"):
        MediaSettings(cdn_domain=domain)


@pytest.mark.parametrize(
    "domain", ["cdn.motionile.com", "d111111abcdef8.cloudfront.net", "localhost", "cdn-1.example.org"]
)
def test_cdn_domain_accepts_host_names(domain: str) -> None:
    assert MediaSettings(cdn_domain=domain).cdn_domain == domain


@pytest.mark.parametrize("key_pair_id", ["K2 JCJ", "K2JCJ-MDE", "a" * 65, "key/pair"])
def test_key_pair_id_must_be_alphanumeric(key_pair_id: str) -> None:
    with pytest.raises(ValidationError):
        MediaSettings(cloudfront_key_pair_id=key_pair_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cookie_ttl_seconds", 59),
        ("cookie_ttl_seconds", 3_601),
        ("signed_url_ttl_seconds", 59),
        ("signed_url_ttl_seconds", 3_601),
    ],
)
def test_media_lifetimes_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        MediaSettings.model_validate({field: value})


@pytest.mark.parametrize("pem", [RSA_PEM, LEGACY_RSA_PEM])
def test_private_key_accepts_pem_rsa_keys(pem: str) -> None:
    media = MediaSettings(cloudfront_private_key=SecretStr(pem))

    assert media.private_key_pem is not None
    assert media.private_key_pem.startswith(b"-----BEGIN")


def test_private_key_accepts_base64_encoded_pem() -> None:
    encoded = base64.b64encode(RSA_PEM.encode()).decode()

    media = MediaSettings(cloudfront_private_key=SecretStr(encoded))

    assert media.private_key_pem == RSA_PEM.strip().encode()


def test_private_key_accepts_pem_with_escaped_newlines() -> None:
    escaped = RSA_PEM.strip().replace("\n", "\\n")

    media = MediaSettings(cloudfront_private_key=SecretStr(escaped))

    assert media.private_key_pem == RSA_PEM.strip().encode()


@pytest.mark.parametrize(
    "value",
    [
        "SECRETMARKER not a key",
        "-----BEGIN PRIVATE KEY-----\nSECRETMARKER\n-----END PRIVATE KEY-----",
        base64.b64encode(b"SECRETMARKER").decode(),
        EC_PEM,
        ENCRYPTED_PEM,
        RSA_PEM[: len(RSA_PEM) // 2],
    ],
)
def test_private_key_must_be_a_pem_rsa_key_and_is_never_echoed(value: str) -> None:
    with pytest.raises(ValidationError, match="PEM RSA private key") as raised:
        MediaSettings(cloudfront_private_key=SecretStr(value))

    message = str(raised.value) + repr(raised.value.errors())
    assert "SECRETMARKER" not in message
    assert value[:60] not in message
    assert "BEGIN PRIVATE KEY" not in message


def test_private_key_from_environment_is_validated_and_never_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFRONT_PRIVATE_KEY", "SECRETMARKER-in-environment")

    with pytest.raises(ValidationError, match="PEM RSA private key") as raised:
        Settings()

    assert "SECRETMARKER" not in str(raised.value)


def test_private_key_is_not_rendered() -> None:
    media = MediaSettings(cloudfront_private_key=SecretStr(RSA_PEM))

    rendered = repr(media) + str(media.model_dump())

    assert "BEGIN PRIVATE KEY" not in rendered
    assert RSA_PEM.splitlines()[1] not in rendered


def test_parse_private_key_pem_returns_the_normalized_pem() -> None:
    assert parse_private_key_pem(f"  {RSA_PEM}  ") == RSA_PEM.strip().encode()


def test_voices_defaults() -> None:
    voices = VoicesSettings()

    assert voices.consent_match_threshold == 0.85
    assert voices.sample_min_total_seconds == 30
    assert voices.sample_max_total_seconds == 300
    assert voices.sample_max_bytes == 26_214_400
    assert voices.consent_max_seconds == 30
    assert voices.consent_min_seconds == 3
    assert voices.attempt_ttl_seconds == 3_600


def test_voices_read_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICES_CONSENT_MATCH_THRESHOLD", "0.9")
    monkeypatch.setenv("VOICES_SAMPLE_MIN_TOTAL_SECONDS", "45")
    monkeypatch.setenv("VOICES_SAMPLE_MAX_TOTAL_SECONDS", "240")
    monkeypatch.setenv("VOICES_SAMPLE_MAX_BYTES", "10485760")
    monkeypatch.setenv("VOICES_CONSENT_MAX_SECONDS", "20")
    monkeypatch.setenv("VOICES_CONSENT_MIN_SECONDS", "4")
    monkeypatch.setenv("VOICES_ATTEMPT_TTL_SECONDS", "1800")

    voices = Settings().voices

    assert voices.consent_match_threshold == 0.9
    assert voices.sample_min_total_seconds == 45
    assert voices.sample_max_total_seconds == 240
    assert voices.sample_max_bytes == 10_485_760
    assert voices.consent_max_seconds == 20
    assert voices.consent_min_seconds == 4
    assert voices.attempt_ttl_seconds == 1_800


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consent_match_threshold", 0.49),
        ("consent_match_threshold", 1.01),
        ("sample_min_total_seconds", 4),
        ("sample_max_total_seconds", 29),
        ("sample_max_total_seconds", 1_801),
        ("sample_max_bytes", 1_048_575),
        ("consent_max_seconds", 2),
        ("consent_min_seconds", 0),
        ("attempt_ttl_seconds", 299),
        ("attempt_ttl_seconds", 86_401),
    ],
)
def test_voices_settings_are_bounded(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        VoicesSettings.model_validate({field: value})


def test_voices_minimums_cannot_exceed_maximums() -> None:
    with pytest.raises(ValidationError, match="SAMPLE_MIN_TOTAL_SECONDS"):
        VoicesSettings(sample_min_total_seconds=200, sample_max_total_seconds=100)
    with pytest.raises(ValidationError, match="CONSENT_MIN_SECONDS"):
        VoicesSettings(consent_min_seconds=30, consent_max_seconds=10)


def test_deployed_environments_accept_the_complete_media_configuration() -> None:
    settings = deployed()

    assert settings.audio_deployment_problems() == []
    assert settings.media_deployment_problems() == []


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_deployed_environments_reject_unset_audio_and_media_settings(env: AppEnv) -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(app=AppSettings(env=env))

    message = str(raised.value)
    for problem in ("ELEVENLABS_API_KEY must be set", "MEDIA_DELIVERY_MODE must be set"):
        assert problem in message
    assert "OPENAI_API_KEY" not in message
    assert "CDN_DOMAIN" not in message


def test_the_delivery_mode_must_be_chosen_explicitly_when_deployed() -> None:
    complete = deployed()
    settings = complete.model_copy(update={"media": MediaSettings()})

    assert settings.media_deployment_problems() == ["MEDIA_DELIVERY_MODE must be set"]


@pytest.mark.parametrize(
    ("tts_provider", "transcriber", "elevenlabs_required", "openai_required"),
    [
        ("elevenlabs", "elevenlabs", True, False),
        ("openai", "openai", False, True),
        ("elevenlabs", "openai", True, True),
        ("openai", "elevenlabs", True, True),
    ],
)
def test_each_selected_audio_provider_needs_its_key_when_deployed(
    tts_provider: str, transcriber: str, elevenlabs_required: bool, openai_required: bool
) -> None:
    complete = deployed()
    settings = complete.model_copy(
        update={
            "audio": AudioSettings.model_validate({"tts_provider": tts_provider, "transcriber": transcriber}),
            "elevenlabs": ElevenLabsSettings(),
            "openai": OpenAISettings(),
        }
    )

    problems = settings.audio_deployment_problems()

    assert ("ELEVENLABS_API_KEY must be set" in problems) is elevenlabs_required
    assert ("OPENAI_API_KEY must be set" in problems) is openai_required


def test_a_provider_key_is_only_required_for_selected_providers() -> None:
    complete = deployed()
    settings = complete.model_copy(
        update={
            "audio": AudioSettings.model_validate({"tts_provider": "openai", "transcriber": "openai"}),
            "elevenlabs": ElevenLabsSettings(),
            "openai": OpenAISettings(api_key=STRONG_SECRET),
        }
    )

    assert settings.audio_deployment_problems() == []


def test_cloudfront_mode_is_accepted_when_complete() -> None:
    settings = cloudfront_settings()

    assert settings.media_deployment_problems() == []
    assert settings.media_cookie_domain == ".motionile.com"


def test_cloudfront_mode_accepts_a_dedicated_cookie_domain() -> None:
    complete = deployed()
    media = MediaSettings.model_validate(
        {
            "delivery_mode": MediaDeliveryMode.CLOUDFRONT,
            "cdn_domain": "cdn.motionile.com",
            "cloudfront_key_pair_id": "K2JCJMDEHXQW5F",
            "cloudfront_private_key": SecretStr(RSA_PEM),
            "cookie_domain": ".media.motionile.com",
        }
    )
    settings = complete.model_copy(
        update={"media": media, "auth": complete.auth.model_copy(update={"cookie_domain": None})}
    )

    assert settings.media_deployment_problems() == []


@pytest.mark.parametrize(
    ("missing", "problem"),
    [
        ("cdn_domain", "CDN_DOMAIN must be set"),
        ("cloudfront_key_pair_id", "CLOUDFRONT_KEY_PAIR_ID must be set"),
        ("cloudfront_private_key", "CLOUDFRONT_PRIVATE_KEY must be set"),
    ],
)
def test_cloudfront_mode_requires_each_signing_value(missing: str, problem: str) -> None:
    complete = cloudfront_settings()
    settings = complete.model_copy(update={"media": complete.media.model_copy(update={missing: None})})

    assert settings.media_deployment_problems() == [problem]


def test_cloudfront_mode_requires_a_cookie_domain() -> None:
    complete = cloudfront_settings()
    settings = complete.model_copy(update={"auth": complete.auth.model_copy(update={"cookie_domain": None})})

    assert settings.media_deployment_problems() == ["MEDIA_COOKIE_DOMAIN or AUTH_COOKIE_DOMAIN must be set"]


def test_presigned_mode_needs_no_cloudfront_values() -> None:
    complete = deployed()

    assert complete.media.delivery_mode is MediaDeliveryMode.PRESIGNED
    assert complete.media.cdn_domain is None
    assert complete.media_deployment_problems() == []


def test_unsafe_media_configuration_is_refused_at_startup() -> None:
    complete = cloudfront_settings()

    with pytest.raises(ValidationError, match="CLOUDFRONT_KEY_PAIR_ID must be set"):
        Settings.model_validate(
            {**complete.model_dump(), "media": complete.media.model_copy(update={"cloudfront_key_pair_id": None})}
        )


ENV_EXAMPLE = Path(__file__).resolve().parents[5] / ".env.example"
MEDIA_ENVIRONMENT_PREFIXES = (
    "MEDIA_",
    "CDN_",
    "CLOUDFRONT_",
    "AUDIO_",
    "ELEVENLABS_",
    "OPENAI_",
    "RENDER_",
    "VOICES_",
)


def example_values() -> dict[str, str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if line.startswith(MEDIA_ENVIRONMENT_PREFIXES):
            name, _, value = line.partition("=")
            values[name] = value
    return values


def test_the_environment_example_lists_every_new_variable_with_the_default_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = example_values()
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.render == RenderSettings.model_validate({})
    assert settings.audio == AudioSettings()
    assert settings.elevenlabs == ElevenLabsSettings()
    assert settings.openai == OpenAISettings()
    assert settings.media.model_dump() == MediaSettings().model_dump()
    assert settings.voices == VoicesSettings()
    assert len(values) == 47


def test_every_new_setting_is_listed_in_the_environment_example() -> None:
    names = set(example_values())

    for group, prefix in (
        (RenderSettings, "RENDER_"),
        (AudioSettings, "AUDIO_"),
        (ElevenLabsSettings, "ELEVENLABS_"),
        (OpenAISettings, "OPENAI_"),
        (VoicesSettings, "VOICES_"),
    ):
        for field in group.model_fields:
            assert f"{prefix}{field.upper()}" in names
    for field in MediaSettings.model_fields.values():
        assert field.validation_alias in names
