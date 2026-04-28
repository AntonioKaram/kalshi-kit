from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kalshi_kit.client.auth import KalshiSigner


def _generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_sign_returns_three_kalshi_headers() -> None:
    signer = KalshiSigner(api_key_id="test-key", private_key=_generate_key())
    headers = signer.sign("GET", "/portfolio/balance", timestamp_ms=1_700_000_000_000)
    assert headers["KALSHI-ACCESS-KEY"] == "test-key"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    assert headers["KALSHI-ACCESS-SIGNATURE"]


def test_signature_verifies_against_public_key() -> None:
    private_key = _generate_key()
    signer = KalshiSigner(api_key_id="test-key", private_key=private_key)
    headers = signer.sign("POST", "/portfolio/orders", timestamp_ms=1_700_000_000_000)
    message = f"{headers['KALSHI-ACCESS-TIMESTAMP']}POST/portfolio/orders".encode()
    private_key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_sign_strips_query_string_from_path() -> None:
    signer = KalshiSigner(api_key_id="test-key", private_key=_generate_key())
    private_key = signer._private_key
    headers = signer.sign("GET", "https://api.kalshi.com/markets?status=open", timestamp_ms=1_700_000_000_000)
    expected_message = f"{headers['KALSHI-ACCESS-TIMESTAMP']}GET/markets".encode()
    private_key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        expected_message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
