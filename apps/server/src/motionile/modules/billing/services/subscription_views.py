from motionile.modules.billing.records import ProductRecord, SubscriptionView
from motionile.modules.billing.schemas import (
    CurrentSubscriptionResponse,
    SubscriptionProductResponse,
    SubscriptionResponse,
)
from motionile.modules.billing.states import ENDED_SUBSCRIPTION_STATUSES


def product_summary(product: ProductRecord) -> SubscriptionProductResponse:
    return SubscriptionProductResponse.model_validate(
        {
            "code": product.code,
            "name": product.name,
            "interval": product.interval,
            "price_paise": product.price_paise,
            "credits_granted": product.credits_granted,
            "plan_key": product.plan_key,
        }
    )


def subscription_response(view: SubscriptionView) -> SubscriptionResponse:
    subscription = view.subscription
    if subscription.status in ENDED_SUBSCRIPTION_STATUSES:
        ends_at = subscription.ended_at
    else:
        ends_at = subscription.current_period_end if subscription.cancel_at_period_end else None
    return SubscriptionResponse.model_validate(
        {
            "id": subscription.id,
            "status": subscription.status.value,
            "product": product_summary(view.product),
            "pending_product": product_summary(view.pending_product) if view.pending_product is not None else None,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "next_charge_at": subscription.next_charge_at,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "cancelled_at": subscription.cancelled_at,
            "ends_at": ends_at,
        }
    )


def current_response(view: SubscriptionView | None) -> CurrentSubscriptionResponse:
    return CurrentSubscriptionResponse(subscription=subscription_response(view) if view is not None else None)
