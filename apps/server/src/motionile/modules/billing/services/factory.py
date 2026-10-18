from dataclasses import dataclass

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.resources import Resources
from motionile.modules.audit import record as record_audit
from motionile.modules.billing.ports import (
    Alert,
    AuditRecorder,
    EventDispatcher,
    Revalidation,
    Savepoint,
    begin_savepoint,
)
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.factory import razorpay_for
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.admin_credits import CreditsAdminService
from motionile.modules.billing.services.admin_payments import PaymentAdminService
from motionile.modules.billing.services.admin_products import ProductAdminDependencies, ProductAdminService
from motionile.modules.billing.services.admin_reconciliation import ReconciliationAdminService
from motionile.modules.billing.services.admin_subscriptions import SubscriptionAdminService
from motionile.modules.billing.services.admin_webhooks import WebhookAdminService
from motionile.modules.billing.services.analytics import AnalyticsService
from motionile.modules.billing.services.customers import CustomerService
from motionile.modules.billing.services.history import HistoryService
from motionile.modules.billing.services.notices import NoticeMailer, NoticeSender
from motionile.modules.billing.services.orders import OrderDependencies, OrderService
from motionile.modules.billing.services.payment_events import PaymentEventHandlers
from motionile.modules.billing.services.products import ProductsService
from motionile.modules.billing.services.receipts import BillingMailer, ReceiptSender
from motionile.modules.billing.services.reconciliation import OrderReconciliation, ReconciliationDependencies
from motionile.modules.billing.services.refund_events import RefundEventHandlers
from motionile.modules.billing.services.refund_settlement import RefundPorts, RefundSettlement
from motionile.modules.billing.services.refunds import RefundDependencies, RefundService
from motionile.modules.billing.services.settlement import SettlementPorts, SettlementService
from motionile.modules.billing.services.settlement_check import SettlementCheck, SettlementCheckDependencies
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
)
from motionile.modules.billing.services.subscriptions import SubscriptionCheckout, SubscriptionDependencies
from motionile.modules.billing.services.verification import PaymentVerificationService
from motionile.modules.billing.services.webhook_processor import ProcessorPorts, WebhookProcessor
from motionile.modules.billing.services.webhook_recovery import RequeuePolicy, WebhookRequeuer
from motionile.modules.billing.services.webhook_registry import HandlerRegistry
from motionile.modules.billing.services.webhooks import WebhookReceiver
from motionile.modules.credits import CreditsService
from motionile.modules.platform import PlatformService

ROLLOVER_SETTING = "billing.subscription_rollover"


@dataclass(frozen=True)
class ServiceHooks:
    dispatch: EventDispatcher
    process_task_name: str
    revalidate: Revalidation
    receipts: ReceiptSender | None = None
    notices: NoticeSender | None = None
    audit: AuditRecorder = record_audit
    alert: Alert = raise_alert
    savepoint: Savepoint = begin_savepoint


@dataclass(frozen=True)
class SubscriptionServices:
    checkout: SubscriptionCheckout
    management: SubscriptionManagement
    finalizer: SubscriptionFinalizer
    sync: SubscriptionSync


@dataclass(frozen=True)
class AdminServices:
    products: ProductAdminService
    payments: PaymentAdminService
    subscriptions: SubscriptionAdminService
    webhooks: WebhookAdminService
    reconciliation: ReconciliationAdminService
    credits: CreditsAdminService
    analytics: AnalyticsService


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
    subscriptions: SubscriptionServices
    refunds: RefundService
    settlement_check: SettlementCheck
    admin: AdminServices


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

    async def subscription_rollover(session: AsyncSession) -> bool:
        return await PlatformService(session, resources.redis_store).setting_value(ROLLOVER_SETTING) is True

    credit_service = CreditsService(resources.clock, billing)
    receipts = hooks.receipts or BillingMailer(resources).payment_receipt
    notices = hooks.notices or NoticeMailer(resources).send
    settlement = SettlementService(
        resources.clock,
        credit_service,
        receipts,
        SettlementPorts(audit=hooks.audit, alert=hooks.alert),
    )
    registry = HandlerRegistry()
    PaymentEventHandlers(settlement).register(registry)
    SubscriptionEventHandlers(
        resources.clock,
        ChargeRecorder(
            resources.clock,
            credit_service,
            ChargePorts(audit=hooks.audit, alert=hooks.alert, rollover=subscription_rollover),
        ),
        SubscriptionHandlerPorts(
            store_factory=SqlBillingRepository, audit=hooks.audit, alert=hooks.alert, notices=notices
        ),
    ).register(registry)
    refund_settlement = RefundSettlement(
        resources.clock,
        credit_service,
        RefundPorts(store_factory=SqlBillingRepository, audit=hooks.audit, alert=hooks.alert, notices=notices),
    )
    RefundEventHandlers(refund_settlement, SqlBillingRepository, hooks.alert).register(registry)
    customers = CustomerService(transaction, razorpay)
    maintenance = MaintenanceDependencies(
        transaction=transaction,
        razorpay=razorpay,
        clock=resources.clock,
        audit=hooks.audit,
        notices=notices,
        alert=hooks.alert,
    )
    subscription_management = SubscriptionManagement(
        ManagementDependencies(transaction, razorpay, resources.clock, key_secret, hooks.audit, notices),
        SqlBillingRepository,
    )
    admin = AdminServices(
        products=ProductAdminService(
            ProductAdminDependencies(
                transaction=transaction,
                razorpay=razorpay,
                redis=resources.redis_store,
                codec=resources.cursor_codec,
                audit=hooks.audit,
                alert=hooks.alert,
                revalidate=hooks.revalidate,
            )
        ),
        payments=PaymentAdminService(transaction, resources.cursor_codec),
        subscriptions=SubscriptionAdminService(transaction, resources.cursor_codec, subscription_management),
        webhooks=WebhookAdminService(transaction, resources.cursor_codec, hooks.dispatch, hooks.audit),
        reconciliation=ReconciliationAdminService(transaction, resources.cursor_codec, resources.storage),
        credits=CreditsAdminService(transaction, resources.cursor_codec, credit_service),
        analytics=AnalyticsService(transaction, resources.clock, credit_service),
    )
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
        subscriptions=SubscriptionServices(
            checkout=SubscriptionCheckout(
                SubscriptionDependencies(
                    transaction, razorpay, customers, resources.clock, billing, key_id, hooks.audit
                ),
                SqlBillingRepository,
            ),
            management=subscription_management,
            finalizer=SubscriptionFinalizer(maintenance),
            sync=SubscriptionSync(maintenance),
        ),
        refunds=RefundService(
            RefundDependencies(
                transaction=transaction,
                razorpay=razorpay,
                settlement=refund_settlement,
                store_factory=SqlBillingRepository,
                audit=hooks.audit,
                alert=hooks.alert,
                clock=resources.clock,
            )
        ),
        settlement_check=SettlementCheck(
            SettlementCheckDependencies(transaction, razorpay, resources.storage, resources.clock, billing),
            alert=hooks.alert,
        ),
        admin=admin,
    )
