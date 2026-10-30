from motionile.engine.ai.llm.models import LlmTask, RouteConfig, RoutingConfig

SONNET = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"
OPUS = "anthropic/claude-opus-5-5"

DEFAULT_ROUTING = RoutingConfig(
    routes={
        LlmTask.GUARD: RouteConfig(
            primary=HAIKU, fallbacks=[SONNET], temperature=0.0, max_output_tokens=512, timeout_seconds=20
        ),
        LlmTask.ROUTE: RouteConfig(
            primary=HAIKU, fallbacks=[SONNET], temperature=0.0, max_output_tokens=1_024, timeout_seconds=30
        ),
        LlmTask.PLAN: RouteConfig(
            primary=SONNET, fallbacks=[OPUS], temperature=0.5, max_output_tokens=8_000, timeout_seconds=120
        ),
        LlmTask.CRITIQUE: RouteConfig(
            primary=SONNET, fallbacks=[OPUS], temperature=0.2, max_output_tokens=3_000, timeout_seconds=90
        ),
        LlmTask.SCENE: RouteConfig(
            primary=SONNET, fallbacks=[OPUS], temperature=0.4, max_output_tokens=12_000, timeout_seconds=180
        ),
        LlmTask.REPAIR: RouteConfig(
            primary=SONNET, fallbacks=[OPUS], temperature=0.2, max_output_tokens=12_000, timeout_seconds=180
        ),
        LlmTask.VISION_REVIEW: RouteConfig(
            primary=SONNET, fallbacks=[OPUS], temperature=0.0, max_output_tokens=3_000, timeout_seconds=120
        ),
        LlmTask.CAPTION: RouteConfig(
            primary=HAIKU, fallbacks=[SONNET], temperature=0.6, max_output_tokens=1_500, timeout_seconds=45
        ),
    }
)


def parse_routing(text: str) -> RoutingConfig:
    return RoutingConfig.model_validate_json(text)


def dump_routing(config: RoutingConfig) -> str:
    return config.model_dump_json(by_alias=True)


DEFAULT_ROUTING_JSON = dump_routing(DEFAULT_ROUTING)
