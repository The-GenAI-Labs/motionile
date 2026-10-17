import asyncio
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from motionile.core.errors import PayloadTooLargeError, ValidationAppError

AVATAR_SIZE = (256, 256)
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
WEBP_HEADER_SIZE = 12


def require_complete_container(source: bytes, image_format: str) -> None:
    if image_format == "JPEG" and not source.endswith(b"\xff\xd9"):
        raise ValidationAppError(code="avatar_polyglot")
    if image_format == "PNG":
        offset = len(PNG_SIGNATURE)
        if not source.startswith(PNG_SIGNATURE):
            raise ValidationAppError(code="avatar_polyglot")
        while offset + 12 <= len(source):
            length = int.from_bytes(source[offset : offset + 4], "big")
            chunk_type = source[offset + 4 : offset + 8]
            offset += length + 12
            if offset > len(source):
                raise ValidationAppError(code="avatar_polyglot")
            if chunk_type == b"IEND":
                if offset != len(source):
                    raise ValidationAppError(code="avatar_polyglot")
                return
        raise ValidationAppError(code="avatar_polyglot")
    if image_format == "WEBP":
        if len(source) < WEBP_HEADER_SIZE or source[:4] != b"RIFF" or source[8:12] != b"WEBP":
            raise ValidationAppError(code="avatar_polyglot")
        if int.from_bytes(source[4:8], "little") + 8 != len(source):
            raise ValidationAppError(code="avatar_polyglot")


def process_avatar_sync(source: bytes, max_bytes: int) -> bytes:
    if len(source) > max_bytes:
        raise PayloadTooLargeError(code="avatar_too_large")
    try:
        with Image.open(io.BytesIO(source)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise ValidationAppError(code="avatar_type_invalid")
            require_complete_container(source, image.format)
            if getattr(image, "n_frames", 1) != 1 or getattr(image, "is_animated", False):
                raise ValidationAppError(code="avatar_animated")
            image.verify()
        with Image.open(io.BytesIO(source)) as image:
            image.load()
            pixels = ImageOps.exif_transpose(image).convert("RGB")
            resized = ImageOps.fit(pixels, AVATAR_SIZE, method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            resized.save(output, format="WEBP", quality=88, method=6, exif=b"")
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        if isinstance(error, ValidationAppError):
            raise
        raise ValidationAppError(code="avatar_type_invalid") from error


async def process_avatar(source: bytes, max_bytes: int) -> bytes:
    return await asyncio.to_thread(process_avatar_sync, source, max_bytes)
