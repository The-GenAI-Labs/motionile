from dataclasses import dataclass

from pydantic import SecretStr

from motionile.core.alerts import raise_alert
from motionile.core.resources import Resources
from motionile.modules.audit import record as record_audit
from motionile.modules.billing.ports import Alert, AuditRecorder, EventDispatcher, Savepoint, begin_savepoint
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.factory import razorpay_for
from motionile.modules.billing.services.customers import CustomerService
from motionile.modules.billing.services.history import HistoryService
from motionile.modules.billing.services.orders import OrderDependencies, OrderService
from motionile.modules.billing.services.payment_events import PaymentEventHandlers
from motionile.modules.billing.services.products import ProductsService
from motionile.modules.billing.services.receipts import BillingMailer, ReceiptSender
from motionile.modules.billing.services.reconciliation import OrderReconciliation, ReconciliationDependencies
from motionile.modules.billing.services.settlement import SettlementPorts, SettlementService
from motionile.modules.billing.services.verification import PaymentVerificationService
from motionile.modules.billing.services.webhook_processor import ProcessorPorts, WebhookProcessor
from motionile.modules.billing.services.webhook_recovery import RequeuePolicy, WebhookRequeuer
from motionile.modules.billing.services.webhook_registry import HandlerRegistry
from motionile.modules.billing.services.webhooks import WebhookReceiver
from motionile.modules.credits import CreditsService


@dataclass(frozen=True)
class ServiceHooks:
    dispatch: EventDispatcher
    process_task_name: str
    receipts: ReceiptSender | None = None
    audit: AuditRecorder = record_audit
    alert: Alert = raise_alert
    savepoint: Savepoint = begin_savepoint


@dataclass(frozen=True)
class BillingServices:
    products: ProductsService
    customers: CustomerService
    orders: OrderService
    verification: PaymentVerificationService
    settlement: SettlementService
    receiver: WebhookReceiver
    processor: WebhookProcessor
    requeuer: WebhookRequeuer
    reconciliation: OrderReconciliation
    history: HistoryService
    registry: HandlerRegistry


def build_services(resources: Resources, hooks: ServiceHooks) -> BillingServices:
    settings = resources.settings
    billing = settings.billing
    transaction = resources.database.transaction
    razorpay = razorpay_for(resources)

    def key_id() -> str:
        return razorpay_credentials(settings).key_id

    def key_secret() -> SecretStr:
        return razorpay_credentials(settings).key_secret

    def webhook_secret() -> SecretStr:
        return razorpay_credentials(settings).webhook_secret

    def max_attempts() -> int:
        return billing.webhook_max_attempts

    receipts = hooks.receipts or BillingMailer(resources).payment_receipt
    settlement = SettlementService(
        resources.clock,
        CreditsService(resources.clock, billing),
        receipts,
        SettlementPorts(audit=hooks.audit, alert=hooks.alert),
    )
    registry = HandlerRegistry()
    PaymentEventHandlers(settlement).register(registry)
    customers = CustomerService(transaction, razorpay)
    return BillingServices(
        products=ProductsService(transaction, resources.redis_store),
        customers=customers,
        orders=OrderService(OrderDependencies(transaction, razorpay, customers, resources.clock, billing, key_id)),
        verification=PaymentVerificationService(transaction, razorpay, settlement, key_secret),
        settlement=settlement,
        receiver=WebhookReceiver(transaction, resources.clock, webhook_secret, hooks.dispatch),
        processor=WebhookProcessor(
            transaction,
            registry,
            resources.clock,
            max_attempts,
            ProcessorPorts(savepoint=hooks.savepoint, alert=hooks.alert),
        ),
        requeuer=WebhookRequeuer(
            transaction, resources.clock, hooks.dispatch, RequeuePolicy(max_attempts, hooks.process_task_name)
        ),
        reconciliation=OrderReconciliation(
            ReconciliationDependencies(transaction, razorpay, settlement, resources.clock, billing)
        ),
        history=HistoryService(transaction, resources.cursor_codec),
        registry=registry,
    )
