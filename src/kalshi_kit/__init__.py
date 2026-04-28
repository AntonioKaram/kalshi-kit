"""kalshi-kit: a Python toolkit for Kalshi prediction-market trading research."""

from __future__ import annotations

from kalshi_kit.broker import Broker, KalshiBroker, PaperBroker, TokenBucketThrottler
from kalshi_kit.client import (
    KalshiRestClient,
    KalshiSigner,
    KalshiWsClient,
    MarketTickerSubscription,
)
from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.orderbook import BinaryOrderBook, BinaryTopOfBook
from kalshi_kit.models.orders import OrderRecord, OrderRequest
from kalshi_kit.models.positions import Position
from kalshi_kit.risk import KillSwitch, RiskConfig, RiskManager, TradeIntent
from kalshi_kit.storage import DuckDBStore
from kalshi_kit.strategy import BaseStrategy, Strategy

__version__ = "0.1.0"

__all__ = [
    "BaseStrategy",
    "BinaryOrderBook",
    "BinaryTopOfBook",
    "Broker",
    "DuckDBStore",
    "FillRecord",
    "KalshiBroker",
    "KalshiRestClient",
    "KalshiSigner",
    "KalshiWsClient",
    "KillSwitch",
    "MarketTickerSubscription",
    "OrderRecord",
    "OrderRequest",
    "PaperBroker",
    "Position",
    "RiskConfig",
    "RiskManager",
    "Strategy",
    "TokenBucketThrottler",
    "TradeIntent",
    "__version__",
]
