from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.subtitles import Cue, build_cues


def narration_cues(narration: NarrationDocument) -> tuple[Cue, ...]:
    words: list[WordTiming] = []
    boundaries: list[int] = []
    for scene in narration.scenes:
        if words and scene.words:
            boundaries.append(len(words))
        words.extend(WordTiming(word.text, word.start_ms, word.end_ms) for word in scene.words)
    return build_cues(words, forced_breaks=boundaries)
