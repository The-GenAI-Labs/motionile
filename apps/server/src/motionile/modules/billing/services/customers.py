from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import UnauthorizedError
from motionile.modules.billing.exceptions import PaymentProviderError
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayError
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.provider import provider_error
from motionile.modules.users import PrimaryContacts, UsersService

FALLBACK_CUSTOMER_NAME = "Motionile customer"

type ContactsLookup = Callable[[AsyncSession, UUID], Awaitable[PrimaryContacts | None]]


@dataclass(frozen=True)
class CustomerProfile:
    razorpay_customer_id: str
    name: str | None
    email: str | None
    contact: str | None


async def users_contacts(session: AsyncSession, user_id: UUID) -> PrimaryContacts | None:
    return await UsersService(session).primary_verified_contacts(user_id)


class CustomerService:
    def __init__(
        self,
        transaction: Transaction,
        razorpay: RazorpayApi,
        *,
        contacts: ContactsLookup = users_contacts,
        store_factory: StoreFactory = SqlBillingRepository,
    ) -> None:
        self._transaction = transaction
        self._razorpay = razorpay
        self._contacts = contacts
        self._store_factory = store_factory

    async def ensure(self, user_id: UUID) -> CustomerProfile:
        async with self._transaction() as session:
            contacts = await self._contacts(session, user_id)
            existing = await self._store_factory(session).customer(user_id)
        if contacts is None:
            raise UnauthorizedError(code="unauthenticated")
        if existing is not None:
            return profile(existing.razorpay_customer_id, contacts)
        try:
            created = await self._razorpay.create_customer(
                name=contacts.name or FALLBACK_CUSTOMER_NAME,
                email=contacts.email,
                contact=contacts.phone,
                notes={"userId": str(user_id)},
            )
        except RazorpayError as error:
            raise provider_error(error) from error
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.insert_customer(user_id, created.id)
            stored = await store.customer(user_id)
        if stored is None:
            raise PaymentProviderError("The payment provider returned a customer that is already in use.")
        return profile(stored.razorpay_customer_id, contacts)


def profile(razorpay_customer_id: str, contacts: PrimaryContacts) -> CustomerProfile:
    return CustomerProfile(
        razorpay_customer_id=razorpay_customer_id,
        name=contacts.name,
        email=contacts.email,
        contact=contacts.phone,
    )
