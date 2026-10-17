from motionile.modules.billing.records import OrderRecord
from motionile.modules.billing.schemas import CheckoutPrefillResponse, CheckoutResponse
from motionile.modules.billing.services.customers import CustomerProfile

CHECKOUT_NAME = "Motionile"


def build_checkout(
    *, order: OrderRecord, product_name: str, key_id: str, customer: CustomerProfile
) -> CheckoutResponse:
    if order.razorpay_order_id is None:
        message = "checkout data needs an order that exists at the payment provider"
        raise ValueError(message)
    return CheckoutResponse(
        order_id=order.id,
        key_id=key_id,
        razorpay_order_id=order.razorpay_order_id,
        amount_paise=order.amount_paise,
        currency=order.currency,
        name=CHECKOUT_NAME,
        description=product_name,
        customer_id=customer.razorpay_customer_id,
        prefill=CheckoutPrefillResponse(name=customer.name, email=customer.email, contact=customer.contact),
    )
