from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiSigner:
    """RSA-PSS request signer for the Kalshi API.

    Kalshi authenticates each request individually: there is no session
    token, no refresh, and no JWT. The client computes a signature over
    `timestamp + method + path` (path-only, no query string, no host) using
    RSA-PSS with SHA-256 and sends three headers:

        KALSHI-ACCESS-KEY
        KALSHI-ACCESS-SIGNATURE
        KALSHI-ACCESS-TIMESTAMP

    The timestamp is milliseconds since the Unix epoch.
    """

    def __init__(self, api_key_id: str, private_key: Any) -> None:
        if not api_key_id:
            raise ValueError("api_key_id is required for signed requests")
        if private_key is None:
            raise ValueError("private_key is required for signed requests")
        self.api_key_id = api_key_id
        self._private_key = private_key

    @classmethod
    def from_pem_file(cls, api_key_id: str, private_key_path: str | Path) -> KalshiSigner:
        path = Path(private_key_path).expanduser()
        with path.open("rb") as handle:
            key = serialization.load_pem_private_key(handle.read(), password=None)
        return cls(api_key_id=api_key_id, private_key=key)

    def sign(self, method: str, path_or_url: str, *, timestamp_ms: int | None = None) -> dict[str, str]:
        """Sign a request and return the three Kalshi auth headers.

        `path_or_url` may be a full URL or a bare path; only the path is
        signed (matching Kalshi's documented scheme).
        """
        ts = str(timestamp_ms if timestamp_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000))
        sign_path = urlparse(path_or_url).path or path_or_url
        message = f"{ts}{method.upper()}{sign_path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
