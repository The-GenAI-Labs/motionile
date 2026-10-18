from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TypedDict, Unpack
from uuid import UUID

import orjson
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.storage import InMemoryStorage
from tests.integration.credit_support import purge_credit_data
from tests.integration.test_auth import csrf

from motionile.core.clock import FrozenClock
from motionile.core.db import Database, after_commit
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.modules.access import grant_role_by_key, invalidate_user_access
from motionile.modules.billing.models import (
    Order,
    Payment,
    Product,
    ReconciliationRun,
    Refund,
    Subscription,
    WebhookEvent,
)
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.factory import fake_store_for, razorpay_for
from motionile.modules.billing.razorpay.fake_entities import PaymentSpec, new_entity_id, payment_entity
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.razorpay.signatures import sign_order_payment, sign_webhook
from motionile.modules.billing.services.factory import BillingServices
from motionile.modules.billing.services.notices import BillingNotice
from motionile.modules.billing.services.receipts import PaymentReceipt
from motionile.modules.billing.tasks import PROCESS_EVENT_TASK
from motionile.modules.credits import CreditsService

PACK_PRICE = 19_900
PACK_CREDITS = 100
SUBSCRIPTION_PRICE = 99_900
SUBSCRIPTION_CREDITS = 500
PROCESS_TASK_NAME = f"motionile:{PROCESS_EVENT_TASK}"
BILLING_TABLES = (
    "webhook_events, billing_reconciliation_runs, refunds, payments, orders, billing_customers, subscriptions, products"
)
FAKE_RAZORPAY = "/v1/_test/razorpay"


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://localhost:8000",
        headers={"Origin": "http://localhost:3000", "X-Turnstile-Token": "test-pass"},
    )


@dataclass
class Recorded:
    dispatched: list[tuple[UUID, bool]] = field(default_factory=list[tuple[UUID, bool]])
    receipts: list[PaymentReceipt] = field(default_factory=list[PaymentReceipt])
    notices: list[BillingNotice] = field(default_factory=list[BillingNotice])
    alerts: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])

    def dispatch(self, session: AsyncSession, event_row_id: UUID, force: bool) -> None:
        async def record() -> None:
            self.dispatched.append((event_row_id, force))

        after_commit(session, record)

    async def receipt(self, session: AsyncSession, receipt: PaymentReceipt) -> None:
        async def record() -> None:
            self.receipts.append(receipt)

        after_commit(session, record)

    async def notice(self, session: AsyncSession, notice: BillingNotice) -> None:
        async def record() -> None:
            self.notices.append(notice)

        after_commit(session, record)

    def alert(self, code: str, **fields: object) -> None:
        self.alerts.append((code, dict(fields)))

    def alert_codes(self) -> list[str]:
        return [code for code, _ in self.alerts]

    def notice_templates(self) -> list[str]:
        return [item.template for item in self.notices]


@dataclass
class BillingApi:
    app: FastAPI
    resources: Resources
    services: BillingServices
    recorded: Recorded
    clock: FrozenClock
    credits: CreditsService
    primary: AsyncClient
    other: AsyncClient
    anonymous: AsyncClient
    primary_id: UUID
    other_id: UUID
    pack_code: str
    keys: Callable[[], str]
    storage: InMemoryStorage

    @property
    def database(self) -> Database:
        return self.resources.database

    def headers(self, client: AsyncClient, key: str | None = None) -> dict[str, str]:
        return {**csrf(client), "Idempotency-Key": key or self.keys()}

    async def create_order(
        self, client: AsyncClient | None = None, *, key: str | None = None, body: dict[str, Any] | None = None
    ) -> Response:
        who = client or self.primary
        return await who.post(
            "/v1/billing/orders",
            json=body if body is not None else {"productCode": self.pack_code},
            headers=self.headers(who, key),
        )

    async def pay(self, razorpay_order_id: str, **body: Any) -> dict[str, Any]:
        response = await self.primary.post(
            f"{FAKE_RAZORPAY}/orders/{razorpay_order_id}/pay", json={"outcome": "success", **body}
        )
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def verify(
        self,
        paid: dict[str, Any],
        client: AsyncClient | None = None,
        *,
        key: str | None = None,
        signature: str | None = None,
    ) -> Response:
        who = client or self.primary
        return await who.post(
            "/v1/billing/payments/verify",
            json={
                "razorpayOrderId": paid["razorpay_order_id"],
                "razorpayPaymentId": paid["razorpay_payment_id"],
                "razorpaySignature": signature or paid["razorpay_signature"],
            },
            headers=self.headers(who, key),
        )

    def sign(self, razorpay_order_id: str, razorpay_payment_id: str) -> str:
        return sign_order_payment(
            razorpay_order_id, razorpay_payment_id, razorpay_credentials(self.resources.settings).key_secret
        )

    async def checkout(self, client: AsyncClient | None = None, *, key: str | None = None) -> dict[str, Any]:
        response = await self.create_order(client, key=key)
        assert response.status_code == 201, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def wallet_balance(self, user_id: UUID) -> int:
        async with self.database.transaction() as session:
            return (await self.credits.wallet(session, user_id)).balance

    async def ledger_rows(self, user_id: UUID) -> list[tuple[str, int, str]]:
        async with self.database.transaction() as session:
            rows = await session.execute(
                text(
                    "SELECT reason, delta, idempotency_key FROM credit_ledger "
                    "WHERE user_id = :user_id ORDER BY created_at, id"
                ),
                {"user_id": user_id},
            )
            return [(row[0], row[1], row[2]) for row in rows]

    async def order_row(self, order_id: UUID | str) -> Order:
        async with self.database.transaction() as session:
            order = await session.scalar(select(Order).where(Order.id == UUID(str(order_id))))
            assert order is not None
            return order

    async def payment_rows(self) -> list[Payment]:
        async with self.database.transaction() as session:
            return list(await session.scalars(select(Payment).order_by(Payment.created_at, Payment.id)))

    async def event_rows(self) -> list[WebhookEvent]:
        async with self.database.transaction() as session:
            return list(await session.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at, WebhookEvent.id)))

    async def event_count(self) -> int:
        async with self.database.transaction() as session:
            return (await session.scalar(select(func.count()).select_from(WebhookEvent))) or 0

    async def audit_actions(self, prefix: str = "billing.") -> list[str]:
        async with self.database.transaction() as session:
            rows = await session.execute(
                text("SELECT action FROM audit_log WHERE action LIKE :prefix ORDER BY created_at, id"),
                {"prefix": f"{prefix}%"},
            )
            return [row[0] for row in rows]

    async def remote_order_count(self) -> int:
        key = self.resources.redis_store.keys.key("fake_razorpay", "sequence", "order")
        raw = await self.resources.redis_store.get(key)
        return int(raw) if raw is not None else 0

    async def process_dispatched(self) -> list[UUID]:
        processed: list[UUID] = []
        while self.recorded.dispatched:
            event_row_id, force = self.recorded.dispatched.pop(0)
            await self.services.processor.process(event_row_id, force=force)
            processed.append(event_row_id)
        return processed

    async def add_captured_payment(self, razorpay_order_id: str, amount: int = PACK_PRICE) -> str:
        store = fake_store_for(self.resources)
        payment_id = await new_entity_id(store, "pay")
        entity = payment_entity(
            payment_id,
            self.clock.now(),
            PaymentSpec(amount=amount, currency="INR", status="captured", order_id=razorpay_order_id),
        )
        await store.put(EntityKind.PAYMENT, payment_id, entity)
        await store.append("order_payments", razorpay_order_id, payment_id)
        await store.append("payments", "all", payment_id)
        return payment_id

    async def plan_product(
        self, code: str | None = None, *, price: int = SUBSCRIPTION_PRICE, credit_amount: int = SUBSCRIPTION_CREDITS
    ) -> str:
        product_code = code or f"plan_{new_id().hex[:12]}"
        plan = await razorpay_for(self.resources).create_plan(
            PlanParams(period=PlanPeriod.MONTHLY, interval=1, name=product_code, amount=price, currency="INR")
        )
        await create_product(
            self.database, product_code, kind="subscription", price=price, credit_amount=credit_amount, plan_id=plan.id
        )
        return product_code

    async def subscribe(
        self,
        code: str,
        client: AsyncClient | None = None,
        *,
        key: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> Response:
        who = client or self.primary
        return await who.post(
            "/v1/billing/subscriptions",
            json=body if body is not None else {"productCode": code},
            headers=self.headers(who, key),
        )

    async def started_subscription(self, code: str, client: AsyncClient | None = None) -> dict[str, Any]:
        response = await self.subscribe(code, client)
        assert response.status_code == 201, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def authorize_subscription(self, razorpay_subscription_id: str, *webhooks: str) -> dict[str, Any]:
        response = await self.primary.post(
            f"{FAKE_RAZORPAY}/subscriptions/{razorpay_subscription_id}/authorize", json={"webhooks": list(webhooks)}
        )
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def verify_subscription(
        self,
        authorized: dict[str, Any],
        client: AsyncClient | None = None,
        *,
        key: str | None = None,
        signature: str | None = None,
    ) -> Response:
        who = client or self.primary
        return await who.post(
            "/v1/billing/subscriptions/verify",
            json={
                "razorpayPaymentId": authorized["razorpay_payment_id"],
                "razorpaySubscriptionId": authorized["razorpay_subscription_id"],
                "razorpaySignature": signature or authorized["razorpay_signature"],
            },
            headers=self.headers(who, key),
        )

    async def transition(
        self, razorpay_subscription_id: str, event: str, *, emit: bool = True, **options: Any
    ) -> dict[str, Any]:
        response = await self.primary.post(
            f"{FAKE_RAZORPAY}/subscriptions/{razorpay_subscription_id}/transition",
            json={"event": event, "emit": emit, **options},
        )
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def activate_subscription(self, code: str, client: AsyncClient | None = None) -> dict[str, Any]:
        started = await self.started_subscription(code, client)
        remote_id = started["razorpaySubscriptionId"]
        authorized = await self.authorize_subscription(remote_id)
        response = await self.verify_subscription(authorized, client)
        assert response.status_code == 200, response.text
        await self.transition(remote_id, "activated")
        await self.deliver(
            event="subscription.charged", subscriptionId=remote_id, paymentId=authorized["razorpay_payment_id"]
        )
        await self.process_dispatched()
        return {**started, **authorized}

    async def renew(self, remote_id: str) -> str:
        moved = await self.transition(remote_id, "charged")
        await self.process_dispatched()
        payment_id: str = moved["razorpayPaymentId"]
        return payment_id

    async def get_subscription(self, client: AsyncClient | None = None) -> dict[str, Any]:
        response = await (client or self.primary).get("/v1/billing/subscription")
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        return payload

    async def end_period(self, subscription_id: UUID | str) -> None:
        now = self.clock.now()
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "UPDATE subscriptions SET current_period_start = :start, current_period_end = :end WHERE id = :id"
                ),
                {"id": UUID(str(subscription_id)), "start": now - timedelta(days=60), "end": now - timedelta(days=1)},
            )

    async def expire_order(self, order_id: UUID | str) -> None:
        async with self.database.transaction() as session:
            await session.execute(
                text("UPDATE orders SET expires_at = :expires_at WHERE id = :id"),
                {"id": UUID(str(order_id)), "expires_at": self.clock.now() - timedelta(minutes=1)},
            )

    async def subscription_row(self, subscription_id: UUID | str) -> Subscription:
        async with self.database.transaction() as session:
            row = await session.scalar(select(Subscription).where(Subscription.id == UUID(str(subscription_id))))
            assert row is not None
            return row

    async def subscription_rows(self) -> list[Subscription]:
        async with self.database.transaction() as session:
            return list(await session.scalars(select(Subscription).order_by(Subscription.created_at, Subscription.id)))

    async def refund_rows(self) -> list[Refund]:
        async with self.database.transaction() as session:
            return list(await session.scalars(select(Refund).order_by(Refund.created_at, Refund.id)))

    async def run_rows(self, run_type: str) -> list[ReconciliationRun]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(ReconciliationRun)
                    .where(ReconciliationRun.type == run_type)
                    .order_by(ReconciliationRun.created_at, ReconciliationRun.id)
                )
            )

    async def lot_rows(self, user_id: UUID | None = None) -> list[tuple[str, int, int, datetime | None]]:
        async with self.database.transaction() as session:
            rows = await session.execute(
                text(
                    "SELECT source, amount, remaining, expires_at FROM credit_lots "
                    "WHERE user_id = :user_id ORDER BY created_at, id"
                ),
                {"user_id": user_id or self.primary_id},
            )
            return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def grant_role(self, user_id: UUID, role: str) -> None:
        async with self.database.transaction() as session:
            await grant_role_by_key(session, self.resources.redis_store, user_id, role)

    async def revoke_roles(self, user_id: UUID) -> None:
        async with self.database.transaction() as session:
            await session.execute(
                text(
                    "DELETE FROM user_roles WHERE user_id = :user_id AND role_id IN "
                    "(SELECT id FROM roles WHERE key IN ('admin', 'super_admin'))"
                ),
                {"user_id": user_id},
            )
        await invalidate_user_access(self.resources.redis_store, user_id)

    async def create_refund(
        self,
        payment_id: UUID | str,
        body: dict[str, Any],
        client: AsyncClient | None = None,
        *,
        key: str | None = None,
    ) -> Response:
        who = client or self.other
        return await who.post(
            f"/v1/admin/billing/payments/{payment_id}/refunds", json=body, headers=self.headers(who, key)
        )

    async def settle_remote_refund(self, razorpay_refund_id: str, outcome: str) -> None:
        response = await self.primary.post(
            f"{FAKE_RAZORPAY}/refunds/{razorpay_refund_id}/settle", json={"outcome": outcome}
        )
        assert response.status_code == 200, response.text

    async def arm_fault(self, operation: str, kind: str, count: int = 1) -> None:
        response = await self.primary.post(
            f"{FAKE_RAZORPAY}/faults", json={"operation": operation, "kind": kind, "count": count}
        )
        assert response.status_code == 200, response.text

    def sign_webhook_body(self, body: bytes) -> str:
        return sign_webhook(body, self.webhook_secret())

    def webhook_secret(self) -> SecretStr:
        return razorpay_credentials(self.resources.settings).webhook_secret

    async def post_webhook(
        self,
        document: dict[str, Any] | bytes,
        *,
        event_id: str | None = None,
        signature: str | None = None,
        sign: bool = True,
        client: AsyncClient | None = None,
    ) -> Response:
        body = document if isinstance(document, bytes) else orjson.dumps(document)
        headers = {"Content-Type": "application/json"}
        if event_id is not None:
            headers["X-Razorpay-Event-Id"] = event_id
        if signature is not None:
            headers["X-Razorpay-Signature"] = signature
        elif sign:
            headers["X-Razorpay-Signature"] = self.sign_webhook_body(body)
        return await (client or self.anonymous).post("/v1/webhooks/razorpay", content=body, headers=headers)

    async def deliver(self, **body: Any) -> dict[str, Any]:
        response = await self.primary.post(f"{FAKE_RAZORPAY}/webhooks", json=body)
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        return payload


class ProductOptions(TypedDict, total=False):
    kind: str
    price: int
    credit_amount: int
    active: bool
    sort_order: int
    plan_id: str


async def create_product(database: Database, code: str, **options: Unpack[ProductOptions]) -> UUID:
    product_id = new_id()
    kind = options.get("kind", "credit_pack")
    credit_amount = options.get("credit_amount", PACK_CREDITS)
    subscription = kind == "subscription"
    async with database.transaction() as session:
        session.add(
            Product(
                id=product_id,
                code=code,
                kind=kind,
                plan_key=f"{code}_plan" if subscription else None,
                name=code.replace("_", " ").title(),
                description=f"{credit_amount} credits",
                price_paise=options.get("price", PACK_PRICE),
                currency="INR",
                interval="month" if subscription else None,
                credits_granted=credit_amount,
                razorpay_plan_id=options.get("plan_id", f"plan_{code}") if subscription else None,
                is_active=options.get("active", True),
                sort_order=options.get("sort_order", 0),
                features=[f"{credit_amount} credits"],
            )
        )
    return product_id


async def purge_billing_data(database: Database, user_ids: list[UUID]) -> None:
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(text(f"TRUNCATE {BILLING_TABLES}"))
    await purge_credit_data(database, [])
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(
            text(
                "DELETE FROM audit_log WHERE actor_user_id = ANY(:ids) "
                "OR action LIKE 'auth.%' OR action LIKE 'billing.%'"
            ),
            {"ids": user_ids},
        )
        await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})
