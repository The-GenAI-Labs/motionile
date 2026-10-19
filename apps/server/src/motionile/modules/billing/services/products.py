import hashlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.redis import RedisStore
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.schemas import ProductResponse, ProductsResponse

CACHE_NAMESPACE = "billing.products"
CACHE_PART = "listing"
CACHE_TTL = timedelta(seconds=60)
CREDIT_PACK = "credit_pack"
SUBSCRIPTION = "subscription"
ETAG_LENGTH = 32
CACHE_CONTROL = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
REVALIDATION_TAG = "billing-products"


@dataclass(frozen=True)
class ProductListing:
    body: bytes
    etag: str


def cache_key(redis: RedisStore) -> str:
    return redis.keys.key(CACHE_NAMESPACE, CACHE_PART)


def etag_for(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:ETAG_LENGTH]}"'


def etag_matches(header: str | None, etag: str) -> bool:
    if header is None:
        return False
    candidates = [candidate.strip() for candidate in header.split(",")]
    if "*" in candidates:
        return True
    return any(candidate.removeprefix("W/") == etag for candidate in candidates)


def product_response(record: ProductRecord) -> ProductResponse:
    return ProductResponse.model_validate(
        {
            "code": record.code,
            "name": record.name,
            "description": record.description,
            "price_paise": record.price_paise,
            "currency": record.currency,
            "interval": record.interval,
            "plan_key": record.plan_key,
            "credits_granted": record.credits_granted,
            "features": list(record.features),
            "sort_order": record.sort_order,
        }
    )


def group_products(records: list[ProductRecord]) -> ProductsResponse:
    return ProductsResponse(
        credit_packs=[product_response(record) for record in records if record.kind == CREDIT_PACK],
        subscriptions=[product_response(record) for record in records if record.kind == SUBSCRIPTION],
    )


async def invalidate_product_cache(redis: RedisStore) -> None:
    await redis.delete(cache_key(redis))


def invalidate_product_cache_after_commit(session: AsyncSession, redis: RedisStore) -> None:
    async def invalidate() -> None:
        await invalidate_product_cache(redis)

    after_commit(session, invalidate)


class ProductsService:
    def __init__(
        self, transaction: Transaction, redis: RedisStore, *, store_factory: StoreFactory = SqlBillingRepository
    ) -> None:
        self._transaction = transaction
        self._redis = redis
        self._store_factory = store_factory

    async def listing(self) -> ProductListing:
        cached = await self._redis.get(cache_key(self._redis))
        if cached is not None:
            return ProductListing(cached, etag_for(cached))
        async with self._transaction() as session:
            records = await self._store_factory(session).active_products()
        body = group_products(records).model_dump_json(by_alias=True).encode()
        await self._redis.set(cache_key(self._redis), body, ttl=CACHE_TTL)
        return ProductListing(body, etag_for(body))
