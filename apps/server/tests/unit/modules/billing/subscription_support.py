from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings
from tests.unit.modules.billing.conftest import BillingHarness

from motionile.core.ids import new_id
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.fake_entities import epoch
from motionile.modules.billing.razorpay.fake_events import (
    WebhookEntities,
    WebhookEventName,
    WebhookReferences,
    build_envelope,
    load_entities,
)
from motionile.modules.billing.razorpay.fake_simulator import (
    RefundOutcome,
    SubscriptionAuthorization,
    SubscriptionEvent,
    SubscriptionTransition,
)
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.razorpay.models import RazorpaySubscription
from motionile.modules.billing.razorpay.signatures import sign_subscription_payment
from motionile.modules.billing.records import NewWebhookEvent, ProductRecord, SubscriptionRecord
from motionile.modules.billing.schemas import SubscriptionCheckoutResponse
from motionile.modules.billing.services.customers import CustomerService
from motionile.modules.billing.services.refund_events import RefundEventHandlers
from motionile.modules.billing.services.refund_settlement import RefundPorts, RefundSettlement
from motionile.modules.billing.services.refunds import RefundDependencies, RefundService
from motionile.modules.billing.services.subscription_charges import ChargePorts, ChargeRecorder
from motionile.modules.billing.services.subscription_events import SubscriptionEventHandlers, SubscriptionHandlerPorts
from motionile.modules.billing.services.subscription_maintenance import (
    MaintenanceDependencies,
    SubscriptionFinalizer,
    SubscriptionSync,
)
from motionile.modules.billing.services.subscription_management import (
    ManagementDependencies,
    SubscriptionManagement,
    VerifySubscriptionCommand,
)
from motionile.modules.billing.services.subscriptions import SubscriptionCheckout, SubscriptionDependencies
from motionile.modules.billing.services.webhook_processor import ProcessingResult, ProcessorPorts, WebhookProcessor
from motionile.modules.billing.services.webhook_registry import HandlerRegistry
from motionile.modules.billing.states import SubscriptionStatus
from motionile.modules.credits import CreditRef, LotRecord
from motionile.modules.users import PrimaryContacts

KEY_ID = "rzp_test_key"
PLAN_PRICE = 99_900
PLAN_CREDITS = 500
CONTACTS = PrimaryContacts(name="Asha Rao", email="asha@example.com", phone="+919876543210")
KEY_SECRET = razorpay_credentials(make_settings()).key_secret
WEBHOOK_ATTEMPTS = 3

type JsonObject = dict[str, Any]


async def known_contacts(session: AsyncSession, user_id: UUID) -> PrimaryContacts | None:
    del session, user_id
    return CONTACTS


@dataclass(frozen=True)
class Delivered:
    event_row_id: UUID
    result: ProcessingResult
    ignored_reason: str | None


@dataclass(frozen=True)
class PreparedEvent:
    name: WebhookEventName
    envelope: JsonObject
    created_at: datetime


class SubscriptionHarness:
    def __init__(self, base: BillingHarness) -> None:
        self.base = base
        self.rollover = False
        self.customers = CustomerService(
            base.world.transaction, base.razorpay, contacts=known_contacts, store_factory=base.billing
        )
        self.checkout = SubscriptionCheckout(
            SubscriptionDependencies(
                base.world.transaction,
                base.razorpay,
                self.customers,
                base.clock,
                base.settings,
                lambda: KEY_ID,
                base.audit,
            ),
            base.billing,
        )
        self.management = SubscriptionManagement(
            ManagementDependencies(
                base.world.transaction,
                base.razorpay,
                base.clock,
                lambda: KEY_SECRET,
                base.audit,
                base.world.send_notice,
            ),
            base.billing,
        )
        charges = ChargeRecorder(base.clock, base.credits, ChargePorts(base.audit, base.world.alert, self._rollover))
        self.registry = HandlerRegistry()
        SubscriptionEventHandlers(
            base.clock,
            charges,
            SubscriptionHandlerPorts(base.billing, base.audit, base.world.alert, base.world.send_notice),
        ).register(self.registry)
        self.refund_settlement = RefundSettlement(
            base.clock,
            base.credits,
            RefundPorts(
                base.billing,
                base.audit,
                base.world.alert,
                base.world.send_notice,
                lot_lookup=self._lot_lookup,
            ),
        )
        RefundEventHandlers(self.refund_settlement, base.billing, base.world.alert, base.audit).register(self.registry)
        self.refunds = RefundService(
            RefundDependencies(
                transaction=base.world.transaction,
                razorpay=base.razorpay,
                settlement=self.refund_settlement,
                store_factory=base.billing,
                audit=base.audit,
                alert=base.world.alert,
                clock=base.clock,
            )
        )
        self.processor = WebhookProcessor(
            base.world.transaction,
            self.registry,
            base.clock,
            lambda: WEBHOOK_ATTEMPTS,
            ProcessorPorts(store_factory=base.billing, savepoint=self._savepoint, alert=base.world.alert),
        )
        maintenance = MaintenanceDependencies(
            transaction=base.world.transaction,
            razorpay=base.razorpay,
            clock=base.clock,
            audit=base.audit,
            notices=base.world.send_notice,
            store_factory=base.billing,
            alert=base.world.alert,
        )
        self.finalizer = SubscriptionFinalizer(maintenance)
        self.sync = SubscriptionSync(maintenance)
        self.plan_counter = 0

    async def _lot_lookup(self, session: AsyncSession, ref: CreditRef) -> LotRecord | None:
        del session
        return await self.base.credits_store.lot_by_reference(ref.ref_type, ref.ref_id)

    async def _rollover(self, session: AsyncSession) -> bool:
        del session
        return self.rollover

    @asynccontextmanager
    async def _savepoint(self, session: AsyncSession) -> AsyncGenerator[None]:
        del session
        billing_state = self.base.billing.snapshot()
        credits_state = self.base.credits_store.snapshot()
        try:
            yield
        except BaseException:
            self.base.billing.restore(billing_state)
            self.base.credits_store.restore(credits_state)
            raise

    async def add_plan(
        self, *, code: str | None = None, price: int = PLAN_PRICE, credit_amount: int = PLAN_CREDITS, name: str = "Pro"
    ) -> ProductRecord:
        self.plan_counter += 1
        plan = await self.base.razorpay.create_plan(
            PlanParams(period=PlanPeriod.MONTHLY, interval=1, name=name, amount=price, currency="INR")
        )
        product = ProductRecord(
            id=new_id(),
            code=code or f"plan_{self.plan_counter}",
            kind="subscription",
            plan_key=f"key_{self.plan_counter}",
            name=name,
            description=f"{credit_amount} credits a month",
            price_paise=price,
            currency="INR",
            interval="month",
            credits_granted=credit_amount,
            razorpay_plan_id=plan.id,
            is_active=True,
            is_sample=False,
            sort_order=self.plan_counter,
            features=(),
            version=1,
        )
        return self.base.billing.add_product(product)

    async def subscribe(
        self, product: ProductRecord, *, user_id: UUID | None = None, key: str | None = None
    ) -> SubscriptionCheckoutResponse:
        self.base.counter += 1
        return await self.checkout.create(
            user_id or self.base.user_id, product.code, key or f"subscribe-{self.base.counter}"
        )

    def local(self, checkout: SubscriptionCheckoutResponse) -> SubscriptionRecord:
        return self.base.billing.subscriptions[checkout.subscription_id]

    def refresh(self, subscription_id: UUID) -> SubscriptionRecord:
        return self.base.billing.subscriptions[subscription_id]

    async def authorize(self, razorpay_subscription_id: str) -> tuple[SubscriptionAuthorization, str]:
        authorization = await self.base.simulator.authorize_subscription(razorpay_subscription_id)
        signature = sign_subscription_payment(authorization.payment["id"], razorpay_subscription_id, KEY_SECRET)
        return authorization, signature

    async def verify(
        self, user_id: UUID, razorpay_subscription_id: str, razorpay_payment_id: str, signature: str | None = None
    ) -> SubscriptionStatus:
        view = await self.management.verify(
            user_id,
            VerifySubscriptionCommand(
                razorpay_payment_id,
                razorpay_subscription_id,
                signature or sign_subscription_payment(razorpay_payment_id, razorpay_subscription_id, KEY_SECRET),
            ),
        )
        return view.subscription.status

    async def advance(self, razorpay_subscription_id: str, event: SubscriptionEvent) -> SubscriptionTransition:
        return await self.base.simulator.transition_subscription(razorpay_subscription_id, event)

    async def prepare(
        self,
        name: WebhookEventName,
        razorpay_subscription_id: str,
        *,
        payment_id: str | None = None,
        created_at: datetime | None = None,
    ) -> PreparedEvent:
        entities: WebhookEntities = await load_entities(
            self.base.razorpay_store,
            name,
            WebhookReferences(payment_id=payment_id, subscription_id=razorpay_subscription_id),
        )
        moment = created_at or self.base.clock.now()
        return PreparedEvent(name, build_envelope(name, entities, created_at=epoch(moment)), moment)

    async def deliver(self, prepared: PreparedEvent, *, event_id: str | None = None) -> Delivered:
        row = NewWebhookEvent(
            id=new_id(),
            provider="razorpay",
            event_id=event_id or f"evt_{new_id().hex}",
            event_type=prepared.name.value,
            event_created_at=prepared.created_at,
            payload=prepared.envelope,
            received_at=self.base.clock.now(),
        )
        assert await self.base.billing.insert_event(row)
        result = await self.processor.process(row.id)
        return Delivered(row.id, result, self.base.billing.events[row.id].ignored_reason)

    async def emit(
        self,
        name: WebhookEventName,
        razorpay_subscription_id: str,
        *,
        payment_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Delivered:
        return await self.deliver(
            await self.prepare(name, razorpay_subscription_id, payment_id=payment_id, created_at=created_at)
        )

    async def remote(self, razorpay_subscription_id: str) -> RazorpaySubscription:
        return await self.base.razorpay.fetch_subscription(razorpay_subscription_id)

    async def activate(self, checkout: SubscriptionCheckoutResponse) -> str:
        authorization, _ = await self.authorize(checkout.razorpay_subscription_id)
        payment_id: str = authorization.payment["id"]
        await self.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
        await self.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, checkout.razorpay_subscription_id)
        await self.emit(WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment_id)
        return payment_id

    async def renew(self, checkout: SubscriptionCheckoutResponse, *, days: int = 30) -> str:
        self.base.clock.advance(timedelta(days=days))
        transition = await self.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CHARGED)
        assert transition.payment is not None
        payment_id: str = transition.payment["id"]
        await self.emit(WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment_id)
        return payment_id

    async def settle_refund(self, razorpay_refund_id: str, outcome: RefundOutcome) -> None:
        await self.base.simulator.settle_refund(razorpay_refund_id, outcome)

    async def emit_refund(self, name: WebhookEventName, razorpay_refund_id: str) -> Delivered:
        entities = await load_entities(self.base.razorpay_store, name, WebhookReferences(refund_id=razorpay_refund_id))
        prepared = PreparedEvent(
            name, build_envelope(name, entities, created_at=epoch(self.base.clock.now())), self.base.clock.now()
        )
        return await self.deliver(prepared)

    async def stored(self, kind: EntityKind, entity_id: str) -> JsonObject:
        entity = await self.base.razorpay_store.get(kind, entity_id)
        assert entity is not None
        return entity

    def lots(self) -> list[Any]:
        return list(self.base.credits_store.lots.values())

    def ledger_keys(self) -> list[str]:
        return [entry.idempotency_key for entry in self.base.credits_store.ledger]

    def set_status(self, subscription_id: UUID, status: SubscriptionStatus, **values: Any) -> SubscriptionRecord:
        return self.patch(subscription_id, status=status, **values)

    def patch(self, subscription_id: UUID, **values: Any) -> SubscriptionRecord:
        updated = replace(self.base.billing.subscriptions[subscription_id], **values)
        self.base.billing.subscriptions[subscription_id] = updated
        return updated

    @staticmethod
    def utc(year: int, month: int, day: int) -> datetime:
        return datetime(year, month, day, tzinfo=UTC)
