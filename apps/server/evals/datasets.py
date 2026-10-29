import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Annotated, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator
from pydantic.alias_generators import to_camel

from evals.errors import DatasetError
from motionile.engine.ai.guardrails.policy import INPUT_REFUSAL_CODES, PolicyCode
from motionile.engine.ai.job_options import AspectName, LanguageCode

DATASETS_ROOT: Final = Path(__file__).parent / "datasets"
GOLDEN_FILE: Final = "golden_queries.yaml"
DURATION_FILE: Final = "duration_cases.yaml"
ADVERSARIAL_FILE: Final = "adversarial.yaml"
VERSION_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}\.\d+$"
CASE_ID_PATTERN: Final = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
MIN_NOTE_WORDS: Final = 60
MAX_NOTE_WORDS: Final = 150
SCENE_SECONDS_FLOOR: Final = 15
SCENE_SECONDS_CEILING: Final = 8
SHORT_RANGE: Final = (10, 20)
LONG_RANGE: Final = (100, 120)
MIN_SCENES: Final = 2
MAX_SCENES: Final = 12

type Phrase = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
type Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
type Aspects = Annotated[list[AspectName], Field(min_length=1, max_length=3)]


class DatasetModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class IdentifiedCase(DatasetModel):
    id: Annotated[str, StringConstraints(pattern=CASE_ID_PATTERN, max_length=60)]


class KeyConcept(DatasetModel):
    name: Phrase
    synonyms: Annotated[list[Phrase], Field(max_length=8)] = Field(default_factory=list[Phrase])

    @property
    def phrases(self) -> tuple[str, ...]:
        return (self.name, *self.synonyms)


def unique_aspects(value: list[AspectName]) -> list[AspectName]:
    if len(set(value)) != len(value):
        raise ValueError("aspects must be unique")
    return value


class GoldenCase(IdentifiedCase):
    subcategory: Annotated[str, StringConstraints(pattern=CASE_ID_PATTERN, max_length=60)]
    query: Query
    duration_seconds: Annotated[int, Field(ge=10, le=120)]
    aspects: Aspects
    language: LanguageCode
    key_concepts: Annotated[list[KeyConcept], Field(min_length=3, max_length=6)]
    misconceptions: Annotated[list[Phrase], Field(min_length=1, max_length=3)]
    reference_notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @field_validator("aspects")
    @classmethod
    def aspects_are_unique(cls, value: list[AspectName]) -> list[AspectName]:
        return unique_aspects(value)

    @field_validator("reference_notes")
    @classmethod
    def notes_have_a_bounded_length(cls, value: str) -> str:
        words = len(value.split())
        if not MIN_NOTE_WORDS <= words <= MAX_NOTE_WORDS:
            raise ValueError(f"referenceNotes needs {MIN_NOTE_WORDS} to {MAX_NOTE_WORDS} words, found {words}")
        return value

    @property
    def duration_ms(self) -> int:
        return self.duration_seconds * 1000


def scene_range_for(duration_seconds: int) -> tuple[int, int]:
    low = max(MIN_SCENES, math.ceil(duration_seconds / SCENE_SECONDS_FLOOR))
    high = min(MAX_SCENES, max(MIN_SCENES, math.ceil(duration_seconds / SCENE_SECONDS_CEILING)))
    return low, high


class DurationCase(IdentifiedCase):
    kind: Literal["short", "long", "multi_aspect"]
    query: Query
    duration_seconds: Annotated[int, Field(ge=10, le=120)]
    aspects: Aspects
    expected_scene_range: tuple[int, int]

    @field_validator("aspects")
    @classmethod
    def aspects_are_unique(cls, value: list[AspectName]) -> list[AspectName]:
        return unique_aspects(value)

    @model_validator(mode="after")
    def kind_matches_the_request(self) -> Self:
        if not self.id.startswith(self.kind.split("_", maxsplit=1)[0]):
            raise ValueError("the id prefix must match the kind")
        if self.kind == "short" and not SHORT_RANGE[0] <= self.duration_seconds <= SHORT_RANGE[1]:
            raise ValueError("short cases last 10 to 20 seconds")
        if self.kind == "long" and not LONG_RANGE[0] <= self.duration_seconds <= LONG_RANGE[1]:
            raise ValueError("long cases last 100 to 120 seconds")
        if self.expected_scene_range != scene_range_for(self.duration_seconds):
            raise ValueError(f"expectedSceneRange must be {list(scene_range_for(self.duration_seconds))}")
        return self

    @property
    def duration_ms(self) -> int:
        return self.duration_seconds * 1000


class AdversarialCase(IdentifiedCase):
    kind: Literal["query", "storyboard_edit", "instructions"]
    text: Annotated[str, StringConstraints(min_length=1, max_length=30_000)]
    expected: Literal["allow", "refuse"]
    expected_code: PolicyCode | None = None
    category: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*$", max_length=60)]

    @model_validator(mode="after")
    def code_matches_expectation(self) -> Self:
        if self.expected == "allow" and self.expected_code is not None:
            raise ValueError("an allowed case carries no expectedCode")
        if self.expected == "refuse":
            if self.expected_code is None:
                raise ValueError("a refused case needs an expectedCode")
            if self.expected_code not in INPUT_REFUSAL_CODES:
                raise ValueError(f"{self.expected_code.value} is not an input refusal code")
        return self

    @property
    def is_probe(self) -> bool:
        return self.category.startswith(("injection_", "extraction_"))


def ensure_unique_ids(cases: Sequence[IdentifiedCase]) -> None:
    identifiers = [case.id for case in cases]
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        raise ValueError(f"case ids must be unique: {', '.join(duplicates)}")
    if not identifiers:
        raise ValueError("a dataset needs at least one case")


class DatasetFile(DatasetModel):
    version: Annotated[str, StringConstraints(pattern=VERSION_PATTERN)]


class GoldenFile(DatasetFile):
    cases: list[GoldenCase]

    @model_validator(mode="after")
    def ids_are_unique(self) -> Self:
        ensure_unique_ids(self.cases)
        return self


class DurationFile(DatasetFile):
    cases: list[DurationCase]

    @model_validator(mode="after")
    def ids_are_unique(self) -> Self:
        ensure_unique_ids(self.cases)
        return self


class AdversarialFile(DatasetFile):
    cases: list[AdversarialCase]

    @model_validator(mode="after")
    def ids_are_unique(self) -> Self:
        ensure_unique_ids(self.cases)
        return self


def read_document(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise DatasetError(f"{path.name}: the file cannot be read ({type(error).__name__})") from error


def parse_file[FileT: DatasetFile](path: Path, file_type: type[FileT]) -> FileT:
    document = read_document(path)
    try:
        return file_type.model_validate(document)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False, include_context=False, include_input=False)[:5]
        )
        raise DatasetError(f"{path.name}: {problems}") from error


def pick[CaseT: IdentifiedCase](cases: Sequence[CaseT], identifiers: Sequence[str] | None, label: str) -> list[CaseT]:
    if identifiers is None:
        return list(cases)
    by_id = {case.id: case for case in cases}
    missing = [identifier for identifier in identifiers if identifier not in by_id]
    if missing:
        raise DatasetError(f"unknown {label} case ids: {', '.join(missing)}")
    return [by_id[identifier] for identifier in identifiers]


@dataclass(frozen=True, slots=True)
class Datasets:
    golden: GoldenFile
    duration: DurationFile
    adversarial: AdversarialFile

    @classmethod
    def load(cls, root: Path = DATASETS_ROOT) -> Self:
        return cls(
            golden=parse_file(root / GOLDEN_FILE, GoldenFile),
            duration=parse_file(root / DURATION_FILE, DurationFile),
            adversarial=parse_file(root / ADVERSARIAL_FILE, AdversarialFile),
        )

    def golden_cases(self, identifiers: Sequence[str] | None = None) -> list[GoldenCase]:
        return pick(self.golden.cases, identifiers, "golden")

    def duration_cases(self, identifiers: Sequence[str] | None = None) -> list[DurationCase]:
        return pick(self.duration.cases, identifiers, "duration")

    def adversarial_cases(self, identifiers: Sequence[str] | None = None) -> list[AdversarialCase]:
        return pick(self.adversarial.cases, identifiers, "adversarial")

    @property
    def versions(self) -> Mapping[str, str]:
        return {
            "golden": self.golden.version,
            "duration": self.duration.version,
            "adversarial": self.adversarial.version,
        }


@cache
def load_datasets(root: Path = DATASETS_ROOT) -> Datasets:
    return Datasets.load(root)
