from collections.abc import Sequence

import pytest

from motionile.engine.ai.llm.models import LlmUnavailableError
from motionile.engine.ai.skills.loader import SkillDocument, SkillLibraryError
from motionile.modules.skills.seed import SeedReport
from motionile.scripts import seed_skills


class FakeResources:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeSeeder:
    def __init__(self, outcome: SeedReport | Exception) -> None:
        self.outcome = outcome
        self.libraries: list[Sequence[SkillDocument]] = []

    async def sync(self, library: Sequence[SkillDocument]) -> SeedReport:
        self.libraries.append(library)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def resources(monkeypatch: pytest.MonkeyPatch) -> FakeResources:
    built = FakeResources()

    def build(settings: object, application_name: str) -> FakeResources:
        del settings, application_name
        return built

    monkeypatch.setattr(seed_skills, "build_resources", build)
    return built


def use_seeder(monkeypatch: pytest.MonkeyPatch, outcome: SeedReport | Exception) -> FakeSeeder:
    seeder = FakeSeeder(outcome)

    def build(resources: object) -> FakeSeeder:
        del resources
        return seeder

    monkeypatch.setattr(seed_skills, "build_skill_seeder", build)
    return seeder


def test_the_script_syncs_the_shipped_library_and_prints_the_report(
    monkeypatch: pytest.MonkeyPatch, resources: FakeResources, capsys: pytest.CaptureFixture[str]
) -> None:
    seeder = use_seeder(monkeypatch, SeedReport(created=30, updated=0, unchanged=0, embedded=30))

    assert seed_skills.main([]) == 0

    assert len(seeder.libraries[0]) == 30
    assert capsys.readouterr().out == "Created 30 skills, updated 0, left 0 unchanged, embedded 30.\n"
    assert resources.closed


def test_the_script_fails_when_the_embeddings_cannot_be_made(
    monkeypatch: pytest.MonkeyPatch, resources: FakeResources, capsys: pytest.CaptureFixture[str]
) -> None:
    use_seeder(monkeypatch, LlmUnavailableError())

    assert seed_skills.main([]) == 1

    assert "llm_unavailable" in capsys.readouterr().err
    assert resources.closed


def test_the_script_fails_before_touching_the_database_when_the_library_is_invalid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> tuple[SkillDocument, ...]:
        raise SkillLibraryError(("domain/physics: the shipped skill is missing",))

    def forbidden(settings: object, application_name: str) -> FakeResources:
        del settings, application_name
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr(seed_skills, "load_library", broken)
    monkeypatch.setattr(seed_skills, "build_resources", forbidden)

    assert seed_skills.main([]) == 1

    assert capsys.readouterr().err == "domain/physics: the shipped skill is missing\n"
