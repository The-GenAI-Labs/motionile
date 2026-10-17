import asyncio
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.credits_ops import USER_COUNT, FakeBackend, Interpreter, Op, build_ops
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.ids import new_id
from motionile.modules.credits import CreditsService
from motionile.modules.credits.domain import LotRecord, allocate, consumption_order

START = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def fake_backend() -> FakeBackend:
    clock = FrozenClock(START)
    users = [new_id() for _ in range(USER_COUNT)]
    store = FakeCreditsStore(clock, set(users))
    service = CreditsService(clock, make_settings().billing, store_factory=store, audit=FakeAudit())
    return FakeBackend(clock, service, store, users)


@settings(max_examples=200, deadline=None)
@given(operations=st.lists(build_ops(), min_size=30, max_size=50))
def test_random_operation_sequences_preserve_every_ledger_invariant(operations: list[Op]) -> None:
    loop = asyncio.new_event_loop()
    try:
        interpreter = Interpreter(fake_backend())
        for operation in operations:
            loop.run_until_complete(interpreter.apply(operation))
            loop.run_until_complete(interpreter.check())
    finally:
        loop.close()


@st.composite
def lots(draw: st.DrawFn) -> list[LotRecord]:
    user_id = new_id()
    count = draw(st.integers(1, 8))
    records: list[LotRecord] = []
    for _ in range(count):
        amount = draw(st.integers(1, 100))
        offset = draw(st.one_of(st.none(), st.integers(0, 5)))
        records.append(
            LotRecord(
                id=new_id(),
                user_id=user_id,
                source="purchase",
                amount=amount,
                remaining=draw(st.integers(1, amount)),
                expires_at=START + timedelta(days=offset) if offset is not None else None,
                ref_type=None,
                ref_id=None,
                created_at=START + timedelta(seconds=draw(st.integers(0, 3))),
            )
        )
    return records


@given(records=lots(), data=st.data())
def test_allocation_follows_consumption_order_and_never_overdraws(
    records: list[LotRecord], data: st.DataObject
) -> None:
    ordered = sorted(records, key=consumption_order)
    total = sum(record.remaining for record in ordered)
    amount = data.draw(st.integers(0, total))

    allocations = allocate(ordered, amount)

    assert sum(item.amount for item in allocations) == amount
    remaining = {record.id: record.remaining for record in ordered}
    assert all(0 < item.amount <= remaining[item.lot_id] for item in allocations)
    positions = [ordered.index(next(record for record in ordered if record.id == item.lot_id)) for item in allocations]
    assert positions == sorted(positions)
    if allocations[:-1]:
        assert all(item.amount == remaining[item.lot_id] for item in allocations[:-1])


@given(records=lots())
def test_non_expiring_lots_are_always_consumed_last(records: list[LotRecord]) -> None:
    ordered = sorted(records, key=consumption_order)
    expiries = [record.expires_at for record in ordered]
    expiring = [value for value in expiries if value is not None]
    assert expiries[: len(expiring)] == expiring
    assert expiring == sorted(expiring)
