import pytest

from motionile.engine.audio.providers.base import ProviderRejectedError
from motionile.engine.audio.providers.transport import (
    MultipartFile,
    RetryPolicy,
    encode_multipart,
    header_safe,
    iso639_1,
    safe_identifier,
)


def test_multipart_body_has_fields_files_and_a_closing_boundary() -> None:
    body, content_type = encode_multipart(
        [("model", "whisper-1"), ("note", "héllo")],
        [MultipartFile("file", "a.wav", b"\x00\x01binary\xff", "audio/wav")],
    )

    boundary = content_type.removeprefix("multipart/form-data; boundary=")
    assert body.startswith(f"--{boundary}\r\n".encode())
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n' in body
    assert "héllo".encode() in body
    assert b'name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n\x00\x01binary\xff\r\n' in body
    assert body.count(f"--{boundary}".encode()) == 4


def test_boundaries_are_random() -> None:
    assert encode_multipart([], [])[1] != encode_multipart([], [])[1]


def test_header_values_cannot_inject_lines_or_quotes() -> None:
    body, _ = encode_multipart([], [MultipartFile("file", 'evil"\r\nX-Injected: 1.wav', b"x", "audio/wav\r\nX: y")])

    assert b"\r\nX-Injected" not in body
    assert b"\r\nX: y" not in body
    assert header_safe('a"b\nc') == "a%22bc"


@pytest.mark.parametrize("value", ["voice_123", "AbC-9", "a" * 128])
def test_safe_identifier_accepts_provider_ids(value: str) -> None:
    assert safe_identifier(value) == value


@pytest.mark.parametrize("value", ["", "../x", "a/b", "a b", "a?b", "é", "a" * 129])
def test_safe_identifier_rejects_everything_else(value: str) -> None:
    with pytest.raises(ProviderRejectedError):
        safe_identifier(value)


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "en"), ("hi-IN", "hi"), ("PT_br", "pt"), ("eng", None), ("", None), (None, None), ("1x", None)],
)
def test_iso_639_1_reduction(language: str | None, expected: str | None) -> None:
    assert iso639_1(language) == expected


def test_retry_backoff_doubles_up_to_the_ceiling() -> None:
    policy = RetryPolicy(base_delay_seconds=0.5, max_delay_seconds=3.0)

    assert [policy.backoff(attempt) for attempt in (1, 2, 3, 4)] == [0.5, 1.0, 2.0, 3.0]
