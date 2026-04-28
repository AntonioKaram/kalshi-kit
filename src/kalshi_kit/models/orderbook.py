from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, Field


class PriceLevel(BaseModel):
    price: float
    size: float


class BinaryTopOfBook(BaseModel):
    yes_bid: float | None = None
    yes_bid_size: float = 0.0
    yes_ask: float | None = None
    yes_ask_size: float = 0.0
    no_bid: float | None = None
    no_bid_size: float = 0.0
    no_ask: float | None = None
    no_ask_size: float = 0.0
    spread_cents: float | None = None
    microprice_yes: float | None = None


class LiquiditySnapshot(BaseModel):
    market_ticker: str
    ts: datetime
    top_of_book: BinaryTopOfBook
    yes_depth: float
    no_depth: float


class BinaryOrderBook(BaseModel):
    market_ticker: str
    ts_event: datetime
    ts_received: datetime
    yes_bids: list[PriceLevel] = Field(default_factory=list)
    no_bids: list[PriceLevel] = Field(default_factory=list)
    sequence: int | None = None

    @staticmethod
    def from_levels(
        market_ticker: str,
        ts_event: datetime,
        ts_received: datetime,
        yes: Iterable[tuple[float, float]],
        no: Iterable[tuple[float, float]],
        *,
        sequence: int | None = None,
    ) -> BinaryOrderBook:
        return BinaryOrderBook(
            market_ticker=market_ticker,
            ts_event=ts_event,
            ts_received=ts_received,
            yes_bids=[PriceLevel(price=p, size=s) for p, s in sorted(yes, reverse=True)],
            no_bids=[PriceLevel(price=p, size=s) for p, s in sorted(no, reverse=True)],
            sequence=sequence,
        )

    def best_yes_bid(self) -> PriceLevel | None:
        return self.yes_bids[0] if self.yes_bids else None

    def best_no_bid(self) -> PriceLevel | None:
        return self.no_bids[0] if self.no_bids else None

    def best_yes_ask(self) -> PriceLevel | None:
        best_no = self.best_no_bid()
        if best_no is None:
            return None
        return PriceLevel(price=max(0.0, 1.0 - best_no.price), size=best_no.size)

    def best_no_ask(self) -> PriceLevel | None:
        best_yes = self.best_yes_bid()
        if best_yes is None:
            return None
        return PriceLevel(price=max(0.0, 1.0 - best_yes.price), size=best_yes.size)

    def yes_depth(self, levels: int = 5) -> float:
        return sum(level.size for level in self.yes_bids[:levels])

    def no_depth(self, levels: int = 5) -> float:
        return sum(level.size for level in self.no_bids[:levels])

    def top_of_book(self) -> BinaryTopOfBook:
        yes_bid = self.best_yes_bid()
        no_bid = self.best_no_bid()
        yes_ask = self.best_yes_ask()
        no_ask = self.best_no_ask()
        spread = None
        if yes_bid and yes_ask:
            spread = max(0.0, (yes_ask.price - yes_bid.price) * 100.0)
        microprice = None
        if yes_bid and yes_ask and yes_bid.size > 0 and yes_ask.size > 0:
            total = yes_bid.size + yes_ask.size
            microprice = (yes_ask.price * yes_bid.size + yes_bid.price * yes_ask.size) / total
        return BinaryTopOfBook(
            yes_bid=yes_bid.price if yes_bid else None,
            yes_bid_size=yes_bid.size if yes_bid else 0.0,
            yes_ask=yes_ask.price if yes_ask else None,
            yes_ask_size=yes_ask.size if yes_ask else 0.0,
            no_bid=no_bid.price if no_bid else None,
            no_bid_size=no_bid.size if no_bid else 0.0,
            no_ask=no_ask.price if no_ask else None,
            no_ask_size=no_ask.size if no_ask else 0.0,
            spread_cents=spread,
            microprice_yes=microprice,
        )

    def apply_delta(self, *, side: str, price: float, delta: float, ts_event: datetime, sequence: int) -> None:
        levels = self.yes_bids if side == "yes" else self.no_bids
        updated: list[PriceLevel] = []
        matched = False
        for level in levels:
            if abs(level.price - price) < 1e-9:
                new_size = level.size + delta
                if new_size > 0:
                    updated.append(PriceLevel(price=price, size=new_size))
                matched = True
            else:
                updated.append(level)
        if not matched and delta > 0:
            updated.append(PriceLevel(price=price, size=delta))
        updated.sort(key=lambda x: x.price, reverse=True)
        if side == "yes":
            self.yes_bids = updated
        else:
            self.no_bids = updated
        self.ts_event = ts_event
        self.sequence = sequence
