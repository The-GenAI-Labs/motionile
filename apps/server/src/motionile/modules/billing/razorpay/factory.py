from motionile.core.resources import Resources
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.client import RazorpayClient
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_simulator import FakeRazorpaySimulator
from motionile.modules.billing.razorpay.fake_store import FakeRazorpayStore, RedisFakeRazorpayStore

RAZORPAY_KEY = "razorpay"
FAKE_STORE_KEY = "razorpay.fake_store"


def fake_store_for(resources: Resources) -> FakeRazorpayStore:
    return resources.shared_instance(FAKE_STORE_KEY, lambda: RedisFakeRazorpayStore(resources.redis_store))


def fake_razorpay_for(resources: Resources) -> FakeRazorpay:
    return FakeRazorpay(fake_store_for(resources), resources.clock)


def fake_simulator_for(resources: Resources) -> FakeRazorpaySimulator:
    return FakeRazorpaySimulator(fake_store_for(resources), resources.clock)


def build_razorpay(resources: Resources) -> RazorpayApi:
    if resources.settings.is_fake_providers:
        return fake_razorpay_for(resources)
    return RazorpayClient(
        resources.provider_clients["razorpay"],
        razorpay_credentials(resources.settings),
        base_url=resources.settings.billing.razorpay_api_base_url,
    )


def razorpay_for(resources: Resources) -> RazorpayApi:
    return resources.shared_instance(RAZORPAY_KEY, lambda: build_razorpay(resources))
