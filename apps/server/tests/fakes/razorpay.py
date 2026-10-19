from dataclasses import dataclass, field

import orjson

from motionile.modules.billing.razorpay.fake_store import Entity, EntityKind, FaultKind, FaultOperation


@dataclass
class ArmedFault:
    kind: FaultKind
    remaining: int


@dataclass
class InMemoryFakeRazorpayStore:
    entities: dict[tuple[EntityKind, str], bytes] = field(default_factory=dict[tuple[EntityKind, str], bytes])
    indexes: dict[tuple[str, str], str] = field(default_factory=dict[tuple[str, str], str])
    lists: dict[tuple[str, str], list[str]] = field(default_factory=dict[tuple[str, str], list[str]])
    sequences: dict[str, int] = field(default_factory=dict[str, int])
    faults: dict[FaultOperation, ArmedFault] = field(default_factory=dict[FaultOperation, ArmedFault])

    async def next_sequence(self, name: str) -> int:
        self.sequences[name] = self.sequences.get(name, 0) + 1
        return self.sequences[name]

    async def get(self, kind: EntityKind, entity_id: str) -> Entity | None:
        raw = self.entities.get((kind, entity_id))
        if raw is None:
            return None
        entity: Entity = orjson.loads(raw)
        return entity

    async def put(self, kind: EntityKind, entity_id: str, entity: Entity) -> None:
        self.entities[kind, entity_id] = orjson.dumps(entity)

    async def set_index(self, name: str, key: str, entity_id: str) -> None:
        self.indexes[name, key] = entity_id

    async def lookup(self, name: str, key: str) -> str | None:
        return self.indexes.get((name, key))

    async def append(self, name: str, key: str, entity_id: str) -> None:
        self.lists.setdefault((name, key), []).append(entity_id)

    async def members(self, name: str, key: str) -> list[str]:
        return list(self.lists.get((name, key), []))

    async def add_fault(self, operation: FaultOperation, kind: FaultKind, count: int) -> None:
        self.faults[operation] = ArmedFault(kind, count)

    async def take_fault(self, operation: FaultOperation) -> FaultKind | None:
        armed = self.faults.get(operation)
        if armed is None or armed.remaining <= 0:
            return None
        armed.remaining -= 1
        return armed.kind

    async def reset(self) -> None:
        self.entities.clear()
        self.indexes.clear()
        self.lists.clear()
        self.sequences.clear()
        self.faults.clear()
