import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from redis.asyncio import Redis

from motionile.core.clock import FrozenClock
from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.modules.billing import RazorpayTimeoutError
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_simulator import FakeRazorpaySimulator, PaymentOutcome
from motionile.modules.billing.razorpay.fake_store import (
    NAMESPACE,
    EntityKind,
    FaultKind,
    FaultOperation,
    RedisFakeRazorpayStore,
)

CLOCK = FrozenClock(datetime(2026, 10, 13, 12, 0, tzinfo=UTC))
CONCURRENCY = 40
KEYS_SCRIPT = "return redis.call('KEYS', ARGV[1])"


async def fake_keys(client: Redis) -> list[bytes]:
    return cast("list[bytes]", await client.eval(KEYS_SCRIPT, 0, f"*:{NAMESPACE}:*"))


@pytest.fixture
def first(redis_client: Redis, redis_keys: RedisKeyBuilder) -> RedisFakeRazorpayStore:
    return RedisFakeRazorpayStore(RedisStore(redis_client, redis_keys))


@pytest.fixture
def second(redis_client: Redis, redis_keys: RedisKeyBuilder) -> RedisFakeRazorpayStore:
    return RedisFakeRazorpayStore(RedisStore(redis_client, redis_keys))


async def test_entities_indexes_and_lists_are_shared_between_instances(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    await first.put(EntityKind.ORDER, "order_a", {"id": "order_a", "amount": 500, "notes": {"k": "v"}, "none": None})
    await first.set_index("receipt", "rcpt with spaces/and:colons", "order_a")
    await first.append("order_payments", "order_a", "pay_1")
    await first.append("order_payments", "order_a", "pay_2")

    assert await second.get(EntityKind.ORDER, "order_a") == {
        "id": "order_a",
        "amount": 500,
        "notes": {"k": "v"},
        "none": None,
    }
    assert await second.lookup("receipt", "rcpt with spaces/and:colons") == "order_a"
    assert await second.members("order_payments", "order_a") == ["pay_1", "pay_2"]
    assert await second.get(EntityKind.ORDER, "order_missing") is None
    assert await second.lookup("receipt", "unknown") is None
    assert await second.members("order_payments", "order_missing") == []


async def test_every_key_expires(first: RedisFakeRazorpayStore, redis_client: Redis) -> None:
    await first.put(EntityKind.PAYMENT, "pay_a", {"id": "pay_a"})
    await first.set_index("receipt", "r", "order_a")
    await first.append("payments", "all", "pay_a")
    await first.next_sequence("pay")
    await first.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 2)
    await first.take_fault(FaultOperation.CREATE_ORDER)

    keys = await fake_keys(redis_client)

    assert len(keys) >= 7
    for key in keys:
        assert 0 < await redis_client.pttl(key) <= int(timedelta(hours=12).total_seconds() * 1000)


async def test_sequences_are_atomic_across_instances(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    results = await asyncio.gather(
        *(store.next_sequence("pay") for _ in range(CONCURRENCY) for store in (first, second))
    )

    assert sorted(results) == list(range(1, 2 * CONCURRENCY + 1))


async def test_a_fault_is_consumed_exactly_its_count_under_concurrency(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    await first.add_fault(FaultOperation.CREATE_REFUND, FaultKind.TIMEOUT_AFTER_CREATE, 3)

    taken = await asyncio.gather(
        *(store.take_fault(FaultOperation.CREATE_REFUND) for _ in range(CONCURRENCY) for store in (first, second))
    )

    assert [fault for fault in taken if fault is not None] == [FaultKind.TIMEOUT_AFTER_CREATE] * 3
    assert await second.take_fault(FaultOperation.CREATE_ORDER) is None


async def test_rearming_a_fault_restarts_the_count(first: RedisFakeRazorpayStore) -> None:
    await first.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 1)
    assert await first.take_fault(FaultOperation.CREATE_ORDER) is FaultKind.SERVER_ERROR
    assert await first.take_fault(FaultOperation.CREATE_ORDER) is None

    await first.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_BEFORE_CREATE, 2)

    assert await first.take_fault(FaultOperation.CREATE_ORDER) is FaultKind.TIMEOUT_BEFORE_CREATE
    assert await first.take_fault(FaultOperation.CREATE_ORDER) is FaultKind.TIMEOUT_BEFORE_CREATE
    assert await first.take_fault(FaultOperation.CREATE_ORDER) is None


async def test_reset_only_removes_fake_razorpay_keys(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore, redis_client: Redis, redis_keys: RedisKeyBuilder
) -> None:
    unrelated = redis_keys.key("oauth.fake_code", "keepme")
    await redis_client.set(unrelated, "kept")
    await first.put(EntityKind.ORDER, "order_a", {"id": "order_a"})
    await first.append("payments", "all", "pay_a")
    await first.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 1)

    await second.reset()

    assert await first.get(EntityKind.ORDER, "order_a") is None
    assert await first.members("payments", "all") == []
    assert await first.take_fault(FaultOperation.CREATE_ORDER) is None
    assert await redis_client.get(unrelated) == b"kept"
    assert await fake_keys(redis_client) == []


async def test_a_fake_razorpay_in_one_process_serves_state_created_in_another(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    api_process = FakeRazorpay(first, CLOCK)
    worker_process = FakeRazorpay(second, CLOCK)

    order = await api_process.create_order(amount=50_000, currency="INR", receipt="shared-receipt")
    await FakeRazorpaySimulator(first, CLOCK).pay_order(order.id, PaymentOutcome.SUCCESS)

    found = await worker_process.find_order_by_receipt("shared-receipt")
    assert found is not None
    assert found.id == order.id
    payments = await worker_process.order_payments(order.id)
    assert [(payment.amount, payment.status) for payment in payments] == [(50_000, "captured")]
    assert (await worker_process.fetch_order(order.id)).status == "paid"


async def test_a_fault_armed_in_one_process_fires_in_the_other(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    api_process = FakeRazorpay(first, CLOCK)
    worker_process = FakeRazorpay(second, CLOCK)
    await first.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    with pytest.raises(RazorpayTimeoutError):
        await worker_process.create_order(amount=500, currency="INR", receipt="lost")

    assert (await api_process.find_order_by_receipt("lost")) is not None
    assert (await worker_process.create_order(amount=500, currency="INR", receipt="fine")).receipt == "fine"


async def test_concurrent_creations_get_distinct_ids(
    first: RedisFakeRazorpayStore, second: RedisFakeRazorpayStore
) -> None:
    fakes = [FakeRazorpay(first, CLOCK), FakeRazorpay(second, CLOCK)]

    orders = await asyncio.gather(
        *(fake.create_order(amount=500, currency="INR", receipt=f"r{index}") for index in range(20) for fake in fakes)
    )

    assert len({order.id for order in orders}) == len(orders)
