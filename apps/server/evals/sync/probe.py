import asyncio
import re
from typing import TYPE_CHECKING, Final

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import Aspect
from motionile.engine.render.sanitize import sanitize_composition

if TYPE_CHECKING:
    from motionile.engine.render.sandbox import RenderSandbox

SEED: Final = 20261024
TOLERANCE_MS: Final = 50.0
ASSOCIATION_MS: Final = 250.0
BUILD_HEADER: Final = re.compile(r"^(?P<indent>\s*)build\(ctx\) \{$", re.MULTILINE)
HEAD_CLOSE: Final = "</head>"

PROBE_SCRIPT: Final = """<script>
window.__moSyncRequests = [];
window.__moProbe = (ctx) => {
  const wrap = (read) => (target, occurrence) => {
    const time = read(target, occurrence);
    window.__moSyncRequests.push({ scene: ctx.id, time });
    return time;
  };
  return Object.freeze({ ...ctx, at: wrap(ctx.at), end: wrap(ctx.end) });
};
</script>
"""

MEASURE_EXPRESSION: Final = """(associationMs) => {
  const requests = window.__moSyncRequests;
  const master = window.__timeline;
  const sceneTimelines = master.getChildren(false, false, true);
  const offsets = [];
  window.__composition.scenes.forEach((scene, index) => {
    const timeline = sceneTimelines[index];
    if (!timeline) {
      return;
    }
    const times = requests.filter((request) => request.scene === scene.id).map((request) => request.time * 1000);
    if (times.length === 0) {
      return;
    }
    for (const tween of timeline.getChildren(true, true, false)) {
      if (!tween.vars || Object.keys(tween.vars).length === 0) {
        continue;
      }
      let start = 0;
      for (let node = tween; node && node !== timeline; node = node.parent) {
        start += node.startTime();
      }
      const startMs = start * 1000;
      const nearest = times.reduce((best, time) => (Math.abs(time - startMs) < Math.abs(best - startMs) ? time : best));
      if (Math.abs(nearest - startMs) <= associationMs) {
        offsets.push(startMs - nearest);
      }
    }
  });
  return offsets;
}"""


def instrument(html: str) -> str:
    wired = BUILD_HEADER.sub(lambda match: f"{match['indent']}build(ctx) {{ ctx = window.__moProbe(ctx);", html)
    return wired.replace(HEAD_CLOSE, f"{PROBE_SCRIPT}{HEAD_CLOSE}", 1)


def within_tolerance(offsets: list[float], tolerance_ms: float = TOLERANCE_MS) -> int:
    return sum(1 for offset in offsets if abs(offset) <= tolerance_ms)


async def measure_offsets(
    sandbox: "RenderSandbox", html: str, narration: NarrationDocument, aspects: list[str]
) -> list[float]:
    from motionile.engine.render.sandbox import PageSpec  # noqa: PLC0415

    sanitized = await asyncio.to_thread(sanitize_composition, html, scene_ids=[s.id for s in narration.scenes])
    probed = instrument(sanitized.html)
    offsets: list[float] = []
    for aspect in aspects:
        spec = PageSpec(html=probed, narration=narration, aspect=Aspect(aspect), seed=SEED)
        async with sandbox.page(spec) as page:
            measured = await page.evaluate(MEASURE_EXPRESSION, ASSOCIATION_MS, what="Measuring word synchronisation")
        offsets.extend(float(value) for value in measured)
    return offsets
