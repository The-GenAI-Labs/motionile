---
name: fastapi-module
description: Patterns for building a Motionile backend module with FastAPI, Pydantic v2, SQLAlchemy 2 async and procrastinate, including router, schemas, service, repository, models, dependencies, exceptions and tests. Use when adding or changing anything under apps/server/src/motionile/modules.
---

# FastAPI module

## Shape

```
modules/<name>/
├── __init__.py        public surface: service, schemas, exceptions
├── router.py          HTTP only: parse, call service, return schema
├── schemas.py         Pydantic request and response models
├── service.py         business logic, authorization, transactions
├── repository.py      SQL only, always scoped by owner
├── models.py          SQLAlchemy models on motionile.core.db.Base
├── dependencies.py    <Thing>Dep aliases
├── exceptions.py      domain errors with stable codes
└── tasks.py           procrastinate tasks, when needed
```

## Schemas

```python
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, alias_generator=to_camel, populate_by_name=True, frozen=True)


class CreateProjectRequest(RequestModel):
    title: Annotated[str, Field(min_length=1, max_length=120)]
```

Bound every string, number and list. Responses use the same camelCase alias generator.

## Dependencies

```python
from typing import Annotated

from fastapi import Depends

ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
```

## Router

```python
router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProject",
    summary="Create a project",
)
async def create_project(body: CreateProjectRequest, service: ProjectServiceDep, user: CurrentUserDep) -> ProjectResponse:
    return await service.create(owner_id=user.id, request=body)
```

Attach the route's rate-limit policy, and raise domain exceptions; the error handler renders RFC 9457 problems with the exception's stable `code`.

## Service and repository

- The service opens the transaction, checks authorization and calls the repository.
- Every repository read takes `owner_id` and filters by it. Never fetch by ID alone.
- Cross-module calls go through the other module's `__init__` exports. Asynchronous side effects publish an event through `core/events.py`.

## Models

- `id` is a UUIDv7 generated in Python with `uuid_utils.uuid7()`.
- `created_at` and `updated_at` are `timestamptz`.
- Status columns are `text` with a `CheckConstraint`. Money and credits are `BigInteger`.
- Index every foreign key; set `ondelete` explicitly.

## Tasks

Register tasks on the queue that matches `motionile.core.tasks.app.Queue`; rendering goes only to `render`. Tasks must be idempotent.

## Tests

- Unit: service with fake repositories from `tests/fakes`.
- Integration: repository and router against testcontainers, each test in a rolled-back transaction.
- Regenerate the API contract with `pnpm contract:generate`.
