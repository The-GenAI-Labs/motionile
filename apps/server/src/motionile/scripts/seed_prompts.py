import argparse
import asyncio
import sys

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.engine.ai.prompts import PromptSourceError, load_prompt_sources
from motionile.modules.prompts import BootstrapRefusedError, build_prompt_seeder, ensure_bootstrap_allowed

EXIT_REFUSED = 2
EXIT_INVALID_SOURCES = 1
BOOTSTRAP_HELP = (
    "activate the latest version of every template without an evaluation; fake-provider environments have "
    "no model to evaluate, and the flag is refused unless APP_ENV is local or ci and PROVIDERS_MODE is fake"
)


async def run(*, bootstrap: bool) -> int:
    settings = get_settings()
    if bootstrap:
        try:
            ensure_bootstrap_allowed(settings.app)
        except BootstrapRefusedError as error:
            sys.stderr.write(f"{error}\n")
            return EXIT_REFUSED
    try:
        sources = await asyncio.to_thread(load_prompt_sources)
    except PromptSourceError as error:
        sys.stderr.write(f"{error}\n")
        return EXIT_INVALID_SOURCES
    resources = build_resources(settings, application_name="motionile-seed-prompts")
    try:
        seeder = build_prompt_seeder(resources)
        report = await seeder.sync(sources)
        activated = await seeder.bootstrap(settings.app) if bootstrap else ()
    finally:
        await resources.aclose()
    sys.stdout.write(
        f"Created {report.templates_created} templates and {len(report.versions_created)} draft versions, "
        f"left {report.unchanged} unchanged, activated {len(activated)} without evaluation.\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync the system prompt files into draft prompt versions.")
    parser.add_argument("--bootstrap-fake-providers", action="store_true", help=BOOTSTRAP_HELP)
    arguments = parser.parse_args(argv)
    return asyncio.run(run(bootstrap=arguments.bootstrap_fake_providers))


if __name__ == "__main__":
    sys.exit(main())
