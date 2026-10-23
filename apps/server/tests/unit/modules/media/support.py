from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

KEY_FILE = Path(__file__).resolve().parents[3] / "fixtures" / "cloudfront" / "rsa-test-key.txt"
KEY_PAIR_ID = "KTESTPAIR0001"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
USER_A = UUID("01939a5e-0000-7000-8000-000000000001")
USER_B = UUID("01939a5e-0000-7000-8000-000000000002")
RENDER = UUID("01939a5e-0000-7000-8000-0000000000aa")


def load_key() -> RSAPrivateKey:
    key = load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    assert isinstance(key, RSAPrivateKey)
    return key
