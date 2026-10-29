from typing import Final

PLANNER_GOLDEN_CHANGED: Final = ("edu-math-01", "edu-bio-01", "tech-backend-01", "tech-ai-01", "tech-security-01")
PLANNER_DURATION_CHANGED: Final = ("short-01", "long-01", "multi-01")
SCENES_FULL: Final = ("edu-math-01", "tech-backend-01", "edu-physics-02", "tech-ai-01")
SCENES_CHANGED: Final = ("edu-math-01", "tech-backend-01")
COST_FULL: Final = ("edu-math-01", "edu-bio-01", "tech-backend-01", "tech-ai-01", "tech-security-01")
COST_CHANGED: Final = ("edu-math-01", "tech-backend-01", "tech-ai-01")
SAFETY_CHANGED: Final = (
    "inj-direct-01",
    "inj-delimiter-01",
    "inj-multilingual-02",
    "inj-edit-01",
    "inj-revision-01",
    "ext-direct-01",
    "ext-canary-01",
    "weapons-01",
    "personal-data-01",
    "allow-injection-topic-01",
    "allow-security-01",
    "allow-edit-01",
)
BENIGN_EDIT_QUERY: Final = "How does binary search work?"
