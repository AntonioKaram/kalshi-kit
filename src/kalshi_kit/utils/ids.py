from __future__ import annotations

import hashlib
import uuid
from datetime import datetime


def make_session_id(prefix: str, ts: datetime) -> str:
    return f"{prefix}-{ts.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"


def deterministic_order_id(
    *,
    session_id: str,
    market_ticker: str,
    side: str,
    action: str,
    price: float,
    size: int,
    nonce: int,
) -> str:
    payload = f"{session_id}|{market_ticker}|{side}|{action}|{price:.4f}|{size}|{nonce}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{session_id[:12]}-{digest}"
