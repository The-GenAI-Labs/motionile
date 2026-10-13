import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class DecryptionError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(f"could not decrypt value: {reason}")


class KeyRing:
    def __init__(self, keys: Mapping[int, bytes]) -> None:
        if not keys:
            message = "a key ring needs at least one key"
            raise ValueError(message)
        for version, key in keys.items():
            if version < 1 or len(key) != KEY_BYTES:
                message = f"key version {version} must be positive and {KEY_BYTES} bytes long"
                raise ValueError(message)
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self.active_version = max(keys)

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> EncryptedValue:
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._ciphers[self.active_version].encrypt(nonce, plaintext, associated_data)
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce, key_version=self.active_version)

    def decrypt(self, value: EncryptedValue, *, associated_data: bytes) -> bytes:
        cipher = self._ciphers.get(value.key_version)
        if cipher is None:
            message = f"unknown key version {value.key_version}"
            raise DecryptionError(message)
        if len(value.nonce) != NONCE_BYTES:
            message = "nonce must be 12 bytes"
            raise DecryptionError(message)
        try:
            return cipher.decrypt(value.nonce, value.ciphertext, associated_data)
        except InvalidTag as error:
            message = "authentication failed"
            raise DecryptionError(message) from error

    def needs_reencryption(self, value: EncryptedValue) -> bool:
        return value.key_version != self.active_version

    def reencrypt(self, value: EncryptedValue, *, associated_data: bytes) -> EncryptedValue:
        return self.encrypt(self.decrypt(value, associated_data=associated_data), associated_data=associated_data)
