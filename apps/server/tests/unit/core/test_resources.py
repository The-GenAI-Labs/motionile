from collections.abc import AsyncIterator

import httpx
import pytest
from tests.fakes.resources import make_resources
from tests.fakes.settings import make_settings

from motionile.core.http.safe_client import OutboundRequestBlockedError
from motionile.core.resources import Resources


@pytest.fixture
async def resources() -> AsyncIterator[Resources]:
    built = make_resources(make_settings())
    yield built
    await built.aclose()


def test_razorpay_client_is_registered_for_the_razorpay_api_host_only(resources: Resources) -> None:
    client = resources.provider_clients["razorpay"]

    assert client.allowed_hosts == frozenset({"api.razorpay.com"})
    assert client is not resources.http_client


async def test_razorpay_client_rejects_other_hosts(resources: Resources) -> None:
    client = resources.provider_clients["razorpay"]

    with pytest.raises(OutboundRequestBlockedError, match="not allowed"):
        await client.validate(httpx.URL("https://api.razorpay.com.evil.example/v1/orders"))
    with pytest.raises(OutboundRequestBlockedError, match="only https"):
        await client.validate(httpx.URL("http://api.razorpay.com/v1/orders"))
