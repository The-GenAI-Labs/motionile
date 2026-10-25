import argparse
import asyncio
import sys

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.engine.ai.llm.models import LlmError
from motionile.engine.ai.skills.loader import SkillLibraryError, load_library
from motionile.modules.skills import build_skill_seeder

EXIT_FAILED = 1


async def run() -> int:
    try:
        library = await asyncio.to_thread(load_library)
    except SkillLibraryError as error:
        for problem in error.problems:
            sys.stderr.write(f"{problem}\n")
        return EXIT_FAILED
    resources = build_resources(get_settings(), application_name="motionile-seed-skills")
    try:
        report = await build_skill_seeder(resources).sync(library)
    except LlmError as error:
        sys.stderr.write(f"The skill descriptions could not be embedded: {error.code.value}\n")
        return EXIT_FAILED
    finally:
        await resources.aclose()
    sys.stdout.write(
        f"Created {report.created} skills, updated {report.updated}, left {report.unchanged} unchanged, "
        f"embedded {report.embedded}.\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize the system skill library with the database and embed the descriptions."
    )
    parser.parse_args(argv)
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
