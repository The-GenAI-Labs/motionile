import hashlib
from datetime import timedelta
from enum import StrEnum
from typing import Any, Protocol

import orjson

from motionile.core.redis import RedisStore

type Entity = dict[str, Any]

NAMESPACE = "fake_razorpay"
STORE_TTL = timedelta(hours=12)
RESET_SCRIPT = "for _, key in ipairs(redis.call('KEYS', ARGV[1])) do redis.call('DEL', key) end return 1"


class EntityKind(StrEnum):
    ORDER = "order"
    PAYMENT = "payment"
    CUSTOMER = "customer"
    PLAN = "plan"
    SUBSCRIPTION = "subscription"
    REFUND = "refund"
    SCHEDULED_CHANGE = "scheduled_change"


class FaultKind(StrEnum):
    TIMEOUT_AFTER_CREATE = "timeout_after_create"
    TIMEOUT_BEFORE_CREATE = "timeout_before_create"
    SERVER_ERROR = "server_error"


class FaultOperation(StrEnum):
    CREATE_ORDER = "create_order"
    FETCH_ORDER = "fetch_order"
    FIND_ORDER_BY_RECEIPT = "find_order_by_receipt"
    ORDER_PAYMENTS = "order_payments"
    FETCH_PAYMENT = "fetch_payment"
    LIST_PAYMENTS = "list_payments"
    CREATE_CUSTOMER = "create_customer"
    CREATE_PLAN = "create_plan"
    CREATE_SUBSCRIPTION = "create_subscription"
    FETCH_SUBSCRIPTION = "fetch_subscription"
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    UPDATE_SUBSCRIPTION = "update_subscription"
    CREATE_REFUND = "create_refund"
    FETCH_REFUND = "fetch_refund"
    LIST_PAYMENT_REFUNDS = "list_payment_refunds"


class FakeRazorpayStore(Protocol):
    async def next_sequence(self, name: str) -> int: ...

    async def get(self, kind: EntityKind, entity_id: str) -> Entity | None: ...

    async def put(self, kind: EntityKind, entity_id: str, entity: Entity) -> None: ...

    async def set_index(self, name: str, key: str, entity_id: str) -> None: ...

    async def lookup(self, name: str, key: str) -> str | None: ...

    async def append(self, name: str, key: str, entity_id: str) -> None: ...

    async def members(self, name: str, key: str) -> list[str]: ...

    async def add_fault(self, operation: FaultOperation, kind: FaultKind, count: int) -> None: ...

    async def take_fault(self, operation: FaultOperation) -> FaultKind | None: ...

    async def reset(self) -> None: ...


def hashed(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RedisFakeRazorpayStore:
    def __init__(self, store: RedisStore) -> None:
        self.store = store

    def _key(self, *parts: str) -> str:
        return self.store.keys.key(NAMESPACE, *parts)

    async def next_sequence(self, name: str) -> int:
        return await self.store.increment(self._key("sequence", name), ttl=STORE_TTL)

    async def get(self, kind: EntityKind, entity_id: str) -> Entity | None:
        raw = await self.store.get(self._key("entity", kind.value, entity_id))
        if raw is None:
            return None
        entity: Entity = orjson.loads(raw)
        return entity

    async def put(self, kind: EntityKind, entity_id: str, entity: Entity) -> None:
        await self.store.set(self._key("entity", kind.value, entity_id), orjson.dumps(entity), ttl=STORE_TTL)

    async def set_index(self, name: str, key: str, entity_id: str) -> None:
        await self.store.set(self._key("index", name, hashed(key)), entity_id, ttl=STORE_TTL)

    async def lookup(self, name: str, key: str) -> str | None:
        raw = await self.store.get(self._key("index", name, hashed(key)))
        return raw.decode() if raw is not None else None

    async def append(self, name: str, key: str, entity_id: str) -> None:
        list_key = self._key("list", name, hashed(key))
        async with self.store.client.pipeline(transaction=True) as pipeline:
            pipeline.rpush(list_key, entity_id)
            pipeline.pexpire(list_key, int(STORE_TTL.total_seconds() * 1000))
            await pipeline.execute()

    async def members(self, name: str, key: str) -> list[str]:
        raw: list[bytes | str] = await self.store.client.lrange(self._key("list", name, hashed(key)), 0, -1)
        return [item.decode() if isinstance(item, bytes) else item for item in raw]

    async def add_fault(self, operation: FaultOperation, kind: FaultKind, count: int) -> None:
        await self.store.delete(self._key("fault", operation, "taken"))
        await self.store.set(self._key("fault", operation, "limit"), str(count), ttl=STORE_TTL)
        await self.store.set(self._key("fault", operation, "kind"), kind.value, ttl=STORE_TTL)

    async def take_fault(self, operation: FaultOperation) -> FaultKind | None:
        limit = await self.store.get(self._key("fault", operation, "limit"))
        kind = await self.store.get(self._key("fault", operation, "kind"))
        if limit is None or kind is None:
            return None
        taken = await self.store.increment(self._key("fault", operation, "taken"), ttl=STORE_TTL)
        return FaultKind(kind.decode()) if taken <= int(limit) else None

    async def reset(self) -> None:
        await self.store.client.eval(RESET_SCRIPT, 0, f"{self.store.keys.prefix}:{NAMESPACE}:*")
