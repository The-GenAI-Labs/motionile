from typing import cast

from motionile.modules.voices.domain import VoiceKind, VoiceStatus
from motionile.modules.voices.models import Voice
from motionile.modules.voices.schemas import AdminVoiceView, VoiceView

TAGS_LABEL = "tags"


def voice_tags(voice: Voice) -> list[str]:
    raw: object = voice.labels.get(TAGS_LABEL)
    if not isinstance(raw, list):
        return []
    items = cast("list[object]", raw)
    return [item for item in items if isinstance(item, str)]


def voice_labels(voice: Voice) -> dict[str, str]:
    return {key: value for key, value in voice.labels.items() if key != TAGS_LABEL and isinstance(value, str)}


def voice_view(voice: Voice) -> VoiceView:
    return VoiceView(
        id=voice.id,
        name=voice.name,
        kind=VoiceKind(voice.kind),
        language=voice.language,
        status=VoiceStatus(voice.status),
        failure_code=voice.failure_code,
        tags=voice_tags(voice),
        labels=voice_labels(voice),
        has_preview=voice.preview_asset_id is not None,
        created_at=voice.created_at,
        updated_at=voice.updated_at,
    )


def admin_voice_view(voice: Voice) -> AdminVoiceView:
    return AdminVoiceView(
        **voice_view(voice).model_dump(),
        provider=voice.provider,
        provider_voice_id=voice.provider_voice_id,
    )
