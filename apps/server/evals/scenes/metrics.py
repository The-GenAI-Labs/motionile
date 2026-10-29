from evals.results import Measurement
from evals.scene_runs import SceneRunArtifacts


def scene_scores(artifacts: SceneRunArtifacts) -> dict[str, Measurement]:
    scenes = artifacts.scene_count
    scores = {
        "sandbox_zero_error_rate": Measurement(artifacts.clean_first_pass / scenes, scenes),
        "fallback_rate": Measurement(artifacts.fallback_scenes / scenes, scenes),
        "repairs_per_scene": Measurement(artifacts.repair_attempts / scenes, scenes),
    }
    if artifacts.static_total:
        scores["static_pass_rate"] = Measurement(
            artifacts.static_passed / artifacts.static_total, artifacts.static_total
        )
    vision = artifacts.vision_score
    if vision is not None:
        scores["vision_review_score"] = Measurement(vision)
    return scores
