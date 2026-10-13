import os
from uuid import UUID

import pytest
from starlette.requests import Request

from motionile.core.errors import UnauthorizedError
from motionile.core.security.encryption import DecryptionError, EncryptedValue, KeyRing
from motionile.core.security.rbac import (
    PermissionDeniedError,
    Principal,
    PrincipalKind,
    principal_of,
    require_permission,
)

KEY_ONE = b"1" * 32
KEY_TWO = b"2" * 32
AAD = b"connected-account:42"


def test_encrypts_and_decrypts_with_associated_data() -> None:
    ring = KeyRing({1: KEY_ONE})

    value = ring.encrypt(b"refresh-token", associated_data=AAD)

    assert value.key_version == 1
    assert len(value.nonce) == 12
    assert b"refresh-token" not in value.ciphertext
    assert ring.decrypt(value, associated_data=AAD) == b"refresh-token"


def test_nonces_are_unique() -> None:
    ring = KeyRing({1: KEY_ONE})

    assert ring.encrypt(b"x", associated_data=AAD).nonce != ring.encrypt(b"x", associated_data=AAD).nonce


def test_rejects_wrong_associated_data() -> None:
    ring = KeyRing({1: KEY_ONE})
    value = ring.encrypt(b"secret", associated_data=AAD)

    with pytest.raises(DecryptionError, match="authentication failed"):
        ring.decrypt(value, associated_data=b"connected-account:43")


def test_rejects_tampered_ciphertext() -> None:
    ring = KeyRing({1: KEY_ONE})
    value = ring.encrypt(b"secret", associated_data=AAD)
    tampered = EncryptedValue(bytes([value.ciphertext[0] ^ 1]) + value.ciphertext[1:], value.nonce, 1)

    with pytest.raises(DecryptionError):
        ring.decrypt(tampered, associated_data=AAD)


def test_rotation_encrypts_with_newest_and_decrypts_old() -> None:
    old_ring = KeyRing({1: KEY_ONE})
    old_value = old_ring.encrypt(b"secret", associated_data=AAD)
    rotated = KeyRing({1: KEY_ONE, 2: KEY_TWO})

    assert rotated.active_version == 2
    assert rotated.decrypt(old_value, associated_data=AAD) == b"secret"
    assert rotated.needs_reencryption(old_value)
    reencrypted = rotated.reencrypt(old_value, associated_data=AAD)
    assert reencrypted.key_version == 2
    assert not rotated.needs_reencryption(reencrypted)


def test_retired_key_cannot_decrypt() -> None:
    value = KeyRing({1: KEY_ONE}).encrypt(b"secret", associated_data=AAD)

    with pytest.raises(DecryptionError, match="unknown key version 1"):
        KeyRing({2: KEY_TWO}).decrypt(value, associated_data=AAD)


def test_rejects_bad_nonce_length() -> None:
    ring = KeyRing({1: KEY_ONE})
    value = ring.encrypt(b"secret", associated_data=AAD)

    with pytest.raises(DecryptionError, match="nonce"):
        ring.decrypt(EncryptedValue(value.ciphertext, os.urandom(8), 1), associated_data=AAD)


@pytest.mark.parametrize("keys", [{}, {1: b"short"}, {0: KEY_ONE}])
def test_rejects_invalid_key_rings(keys: dict[int, bytes]) -> None:
    with pytest.raises(ValueError, match="key"):
        KeyRing(keys)


def user(*, roles: frozenset[str] = frozenset(), permissions: frozenset[str] = frozenset()) -> Principal:
    return Principal(kind=PrincipalKind.USER, user_id=UUID(int=1), roles=roles, permissions=permissions)


def test_permissions_are_checked() -> None:
    principal = user(permissions=frozenset({"users.read"}))

    assert require_permission(principal, "users.read") is principal
    with pytest.raises(PermissionDeniedError) as raised:
        require_permission(principal, "users.write")
    assert raised.value.code == "permission_denied"


def test_super_admin_and_system_have_every_permission() -> None:
    assert user(roles=frozenset({"super_admin"})).has_permission("anything.at_all")
    assert Principal(kind=PrincipalKind.SYSTEM).has_permission("anything.at_all")
    assert user(roles=frozenset({"admin"})).has_role("admin")


def test_missing_principal_is_unauthorized() -> None:
    with pytest.raises(UnauthorizedError):
        require_permission(None, "users.read")


def test_principal_of_reads_request_state() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {}})
    assert principal_of(request) is None

    request.state.principal = user()
    assert principal_of(request) == user()

    request.state.principal = "not a principal"
    assert principal_of(request) is None
