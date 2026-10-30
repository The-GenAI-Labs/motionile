import hashlib

from motionile.engine.ai.storyboard import Storyboard

DIGEST_CHARS = 16


def storyboard_texts(storyboard: Storyboard) -> set[str]:
    texts = {storyboard.title, storyboard.summary}
    for scene in storyboard.scenes:
        texts.update((scene.goal, scene.narration, scene.visual_brief))
        texts.update(scene.layout_notes.values())
        texts.update(scene.key_terms)
        texts.update(scene.on_screen_text)
    return texts


def changed_texts(previous: Storyboard, edited: Storyboard) -> list[str]:
    return sorted(storyboard_texts(edited) - storyboard_texts(previous))


def instructions_digest(instructions: str) -> str:
    return hashlib.sha256(instructions.encode("utf-8")).hexdigest()[:DIGEST_CHARS]
