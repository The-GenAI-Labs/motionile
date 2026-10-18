from typing import cast
from uuid import UUID

from motionile.core.errors import UnauthorizedError
from motionile.core.logging import redact
from motionile.core.security.rbac import Principal
from motionile.modules.billing.admin_credit_schemas import (
    AdminLedgerEntryResponse,
    AdminUserCreditsResponse,
    CreditsAnalyticsResponse,
    CreditsDayResponse,
    CreditsGrantedResponse,
    CreditsTotalsResponse,
    PlanCountResponse,
    RevenueAnalyticsResponse,
    RevenueDayResponse,
    RevenueDayTotalsResponse,
    SubscriptionAnalyticsResponse,
)
from motionile.modules.billing.admin_records import (
    EventDetail,
    EventSummary,
    OrderRow,
    PaymentDetail,
    PaymentRow,
    ProductDetail,
    ProductLink,
    ProductRow,
    RefundRow,
    RunRow,
    SubscriptionRow,
)
from motionile.modules.billing.admin_schemas import (
    AdminLotResponse,
    AdminOrderDetailResponse,
    AdminOrderResponse,
    AdminPaymentDetailResponse,
    AdminPaymentResponse,
    AdminProductDetailResponse,
    AdminProductResponse,
    AdminRefundResponse,
    AdminRunResponse,
    AdminSubscriptionDetailResponse,
    AdminSubscriptionProductResponse,
    AdminSubscriptionResponse,
    AdminWebhookEventDetailResponse,
    AdminWebhookEventResponse,
    ClawbackPreviewResponse,
    PaymentSubscriptionResponse,
    ProductLinkResponse,
    WebhookReprocessResponse,
)
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.services.admin_credits import UserCredits
from motionile.modules.billing.services.admin_subscriptions import SubscriptionDetail
from motionile.modules.billing.services.analytics import CreditsReport, RevenueReport, SubscriptionReport
from motionile.modules.billing.services.analytics_rules import CreditsDay
from motionile.modules.credits import LedgerRecord, LotRecord


def actor_of(principal: Principal) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


def product_fields(row: ProductRow) -> dict[str, object]:
    record = row.record
    return {
        "id": record.id,
        "code": record.code,
        "kind": record.kind,
        "plan_key": record.plan_key,
        "name": record.name,
        "description": record.description,
        "price_paise": record.price_paise,
        "currency": record.currency,
        "interval": record.interval,
        "credits_granted": record.credits_granted,
        "razorpay_plan_id": record.razorpay_plan_id,
        "is_active": record.is_active,
        "is_sample": record.is_sample,
        "sort_order": record.sort_order,
        "features": list(record.features),
        "version": record.version,
        "is_used": row.is_used,
        "supersedes_product_id": row.supersedes_product_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def product_response(row: ProductRow) -> AdminProductResponse:
    return AdminProductResponse.model_validate(product_fields(row))


def link_response(link: ProductLink) -> ProductLinkResponse:
    return ProductLinkResponse(id=link.id, code=link.code, name=link.name, version=link.version)


def product_detail_response(detail: ProductDetail) -> AdminProductDetailResponse:
    return AdminProductDetailResponse.model_validate(
        {
            **product_fields(detail.row),
            "supersedes": link_response(detail.links.supersedes) if detail.links.supersedes is not None else None,
            "superseded_by": [link_response(link) for link in detail.links.superseded_by],
        }
    )


def order_fields(row: OrderRow) -> dict[str, object]:
    order = row.order
    return {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status.value,
        "kind": order.kind,
        "product_id": order.product_id,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "product_version": order.product_version,
        "amount_paise": order.amount_paise,
        "currency": order.currency,
        "credits_granted": order.credits_granted,
        "razorpay_order_id": order.razorpay_order_id,
        "subscription_id": order.subscription_id,
        "receipt": order.receipt,
        "failure_reason": order.failure_reason,
        "flagged_at": order.flagged_at,
        "flag_reason": order.flag_reason,
        "expires_at": order.expires_at,
        "paid_at": order.paid_at,
        "created_at": order.created_at,
    }


def order_response(row: OrderRow) -> AdminOrderResponse:
    return AdminOrderResponse.model_validate(order_fields(row))


def payment_fields(row: PaymentRow) -> dict[str, object]:
    payment = row.payment
    return {
        "id": payment.id,
        "razorpay_payment_id": payment.razorpay_payment_id,
        "user_id": payment.user_id,
        "order_id": payment.order_id,
        "subscription_id": payment.subscription_id,
        "status": payment.status.value,
        "amount_paise": payment.amount_paise,
        "currency": payment.currency,
        "method": payment.method,
        "fee_paise": payment.fee_paise,
        "tax_paise": payment.tax_paise,
        "credits_granted": payment.credits_granted,
        "refunded_paise": payment.refunded_paise,
        "error_code": payment.error_code,
        "error_description": payment.error_description,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "flagged": row.flagged,
        "captured_at": payment.captured_at,
        "created_at": payment.created_at,
    }


def payment_response(row: PaymentRow) -> AdminPaymentResponse:
    return AdminPaymentResponse.model_validate(payment_fields(row))


def order_detail_response(row: OrderRow, payments: list[PaymentRow]) -> AdminOrderDetailResponse:
    return AdminOrderDetailResponse.model_validate(
        {**order_fields(row), "payments": [payment_response(payment) for payment in payments]}
    )


def refund_response(row: RefundRow) -> AdminRefundResponse:
    refund = row.refund
    return AdminRefundResponse.model_validate(
        {
            "id": refund.id,
            "payment_id": refund.payment_id,
            "user_id": row.user_id,
            "status": refund.status.value,
            "amount_paise": refund.amount_paise,
            "currency": row.currency,
            "payment_amount_paise": row.payment_amount_paise,
            "reason": refund.reason,
            "credits_clawed_back": refund.credits_clawed_back,
            "razorpay_refund_id": refund.razorpay_refund_id,
            "initiated_by": refund.initiated_by,
            "failure_reason": refund.failure_reason,
            "processed_at": refund.processed_at,
            "created_at": refund.created_at,
        }
    )


def lot_response(lot: LotRecord) -> AdminLotResponse:
    return AdminLotResponse.model_validate(lot)


def payment_subscription_response(row: SubscriptionRow) -> PaymentSubscriptionResponse:
    return PaymentSubscriptionResponse.model_validate(
        {
            "id": row.subscription.id,
            "status": row.subscription.status.value,
            "product_code": row.product.code,
            "product_name": row.product.name,
            "plan_key": row.product.plan_key,
            "interval": row.product.interval,
        }
    )


def payment_detail_response(detail: PaymentDetail) -> AdminPaymentDetailResponse:
    payment = detail.row.payment
    refunds = [
        AdminRefundResponse.model_validate(
            {
                "id": refund.id,
                "payment_id": refund.payment_id,
                "user_id": payment.user_id,
                "status": refund.status.value,
                "amount_paise": refund.amount_paise,
                "currency": payment.currency,
                "payment_amount_paise": payment.amount_paise,
                "reason": refund.reason,
                "credits_clawed_back": refund.credits_clawed_back,
                "razorpay_refund_id": refund.razorpay_refund_id,
                "initiated_by": refund.initiated_by,
                "failure_reason": refund.failure_reason,
                "processed_at": refund.processed_at,
                "created_at": refund.created_at,
            }
        )
        for refund in detail.refunds
    ]
    return AdminPaymentDetailResponse.model_validate(
        {
            **payment_fields(detail.row),
            "order": order_response(detail.order) if detail.order is not None else None,
            "subscription": (
                payment_subscription_response(detail.subscription) if detail.subscription is not None else None
            ),
            "refunds": refunds,
            "lot": lot_response(detail.lot) if detail.lot is not None else None,
            "refundable_paise": detail.refundable_paise,
            "pending_refund_paise": detail.pending_refund_paise,
            "clawback_preview": ClawbackPreviewResponse(
                amount_paise=detail.preview_amount_paise, credits_to_claw_back=detail.credits_to_claw_back
            ),
        }
    )


def subscription_product(record: ProductRecord) -> AdminSubscriptionProductResponse:
    return AdminSubscriptionProductResponse.model_validate(
        {
            "id": record.id,
            "code": record.code,
            "name": record.name,
            "plan_key": record.plan_key,
            "interval": record.interval,
            "price_paise": record.price_paise,
            "credits_granted": record.credits_granted,
            "is_active": record.is_active,
        }
    )


def subscription_fields(row: SubscriptionRow) -> dict[str, object]:
    subscription = row.subscription
    return {
        "id": subscription.id,
        "user_id": subscription.user_id,
        "status": subscription.status.value,
        "razorpay_subscription_id": subscription.razorpay_subscription_id,
        "product": subscription_product(row.product),
        "pending_product": subscription_product(row.pending_product) if row.pending_product is not None else None,
        "total_count": subscription.total_count,
        "paid_count": subscription.paid_count,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "next_charge_at": subscription.next_charge_at,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "cancelled_at": subscription.cancelled_at,
        "ended_at": subscription.ended_at,
        "created_at": subscription.created_at,
    }


def subscription_response(row: SubscriptionRow) -> AdminSubscriptionResponse:
    return AdminSubscriptionResponse.model_validate(subscription_fields(row))


def subscription_detail_response(detail: SubscriptionDetail) -> AdminSubscriptionDetailResponse:
    return AdminSubscriptionDetailResponse.model_validate(
        {
            **subscription_fields(detail.row),
            "payments": [payment_response(payment) for payment in detail.payments],
            "orders": [order_response(order) for order in detail.orders],
        }
    )


def event_fields(event: EventSummary) -> dict[str, object]:
    return {
        "id": event.id,
        "provider": event.provider,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "event_created_at": event.event_created_at,
        "status": event.status.value,
        "attempts": event.attempts,
        "last_error": event.last_error,
        "ignored_reason": event.ignored_reason,
        "received_at": event.received_at,
        "processed_at": event.processed_at,
    }


def event_response(event: EventSummary) -> AdminWebhookEventResponse:
    return AdminWebhookEventResponse.model_validate(event_fields(event))


def event_detail_response(detail: EventDetail) -> AdminWebhookEventDetailResponse:
    return AdminWebhookEventDetailResponse.model_validate(
        {**event_fields(detail.summary), "payload": cast("dict[str, object]", redact(detail.payload))}
    )


def reprocess_response(event: EventSummary) -> WebhookReprocessResponse:
    return WebhookReprocessResponse.model_validate(
        {"id": event.id, "previous_status": event.status.value, "queued": True}
    )


def run_response(run: RunRow) -> AdminRunResponse:
    return AdminRunResponse.model_validate(
        {
            "id": run.id,
            "type": run.type,
            "status": run.status.value,
            "period_start": run.period_start,
            "period_end": run.period_end,
            "checked_count": run.checked_count,
            "repaired_count": run.repaired_count,
            "mismatch_count": run.mismatch_count,
            "summary": run.summary,
            "has_report": run.report_storage_key is not None,
            "error": run.error,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
        }
    )


def ledger_response(entry: LedgerRecord) -> AdminLedgerEntryResponse:
    return AdminLedgerEntryResponse.model_validate(entry)


def user_credits_response(holdings: UserCredits) -> AdminUserCreditsResponse:
    return AdminUserCreditsResponse(
        user_id=holdings.user_id,
        balance=holdings.wallet.balance,
        reserved=holdings.wallet.reserved,
        available=holdings.wallet.available,
        lots=[lot_response(lot) for lot in holdings.lots.items],
        next_cursor=holdings.lots.next_cursor,
    )


def revenue_response(report: RevenueReport) -> RevenueAnalyticsResponse:
    days = [
        RevenueDayResponse(
            date=day.day,
            captured_paise=day.captured_paise,
            refunded_paise=day.refunded_paise,
            net_paise=day.captured_paise - day.refunded_paise,
            payment_count=day.payment_count,
        )
        for day in report.days
    ]
    return RevenueAnalyticsResponse(
        range_start=report.window.start,
        range_end=report.window.end,
        currency="INR",
        days=days,
        totals=RevenueDayTotalsResponse(
            captured_paise=sum(day.captured_paise for day in days),
            refunded_paise=sum(day.refunded_paise for day in days),
            net_paise=sum(day.net_paise for day in days),
            payment_count=sum(day.payment_count for day in days),
        ),
    )


def subscription_analytics_response(report: SubscriptionReport) -> SubscriptionAnalyticsResponse:
    return SubscriptionAnalyticsResponse(
        total_live=sum(plan.live_count for plan in report.by_plan),
        total_active=sum(plan.active_count for plan in report.by_plan),
        by_plan=[
            PlanCountResponse(
                plan_key=plan.plan_key,
                product_code=plan.product_code,
                product_name=plan.product_name,
                interval=plan.interval,
                live_count=plan.live_count,
                active_count=plan.active_count,
            )
            for plan in report.by_plan
        ],
        by_status=report.by_status,
    )


def granted_response(values: dict[str, int]) -> CreditsGrantedResponse:
    return CreditsGrantedResponse(
        purchase=values["purchase"], subscription=values["subscription"], promo=values["promo"], admin=values["admin"]
    )


def credits_day_response(day: CreditsDay) -> CreditsDayResponse:
    return CreditsDayResponse(
        date=day.day,
        granted=granted_response(dict(day.granted)),
        granted_total=day.granted_total,
        consumed=day.consumed,
        expired=day.expired,
        clawed_back=day.clawed_back,
        adjusted_down=day.adjusted_down,
    )


def credits_analytics_response(report: CreditsReport) -> CreditsAnalyticsResponse:
    totals_granted = {
        source: sum(day.granted[source] for day in report.days)
        for source in ("purchase", "subscription", "promo", "admin")
    }
    return CreditsAnalyticsResponse(
        range_start=report.window.start,
        range_end=report.window.end,
        days=[credits_day_response(day) for day in report.days],
        totals=CreditsTotalsResponse(
            granted=granted_response(totals_granted),
            granted_total=sum(totals_granted.values()),
            consumed=sum(day.consumed for day in report.days),
            expired=sum(day.expired for day in report.days),
            clawed_back=sum(day.clawed_back for day in report.days),
            adjusted_down=sum(day.adjusted_down for day in report.days),
        ),
        wallets=report.balances.wallets,
        balance=report.balances.balance,
        reserved=report.balances.reserved,
    )
