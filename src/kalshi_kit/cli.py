"""kalshi-kit command-line interface."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import typer

from kalshi_kit import __version__
from kalshi_kit.analysis.diagnostics import diagnose_session
from kalshi_kit.analysis.lag_correlation import compute_session_lag_correlation
from kalshi_kit.client.rest import KalshiRestClient

app = typer.Typer(help="kalshi-kit - Kalshi prediction-market toolkit")


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def diagnose(
    session: Path = typer.Option(..., "--session", help="Path to a recorded DuckDB session."),
    per_session: bool = typer.Option(False, "--per-session", help="Print per-session breakdown."),
) -> None:
    result = diagnose_session(Path(session))
    typer.echo(_to_json(result))
    if per_session:
        typer.echo(json.dumps({"per_session": True, "session": str(session)}, indent=2))


@app.command("diagnose-lag")
def diagnose_lag(
    session: Path = typer.Option(..., "--session", help="Path to a recorded DuckDB session."),
) -> None:
    result = compute_session_lag_correlation(Path(session))
    typer.echo(_to_json(result))


@app.command("discover-markets")
def discover_markets(
    event_ticker: str = typer.Option(..., "--event-ticker", help="Event ticker prefix, e.g. KXBTC."),
    status: str = typer.Option("open", "--status", help="Market status filter."),
) -> None:
    try:
        markets = asyncio.run(_discover_markets(event_ticker=event_ticker, status=status))
    except RuntimeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(markets, default=str, indent=2))


async def _discover_markets(*, event_ticker: str, status: str) -> object:
    rest = KalshiRestClient.from_env()
    try:
        return await rest.get_markets(event_ticker=event_ticker, status=status)
    finally:
        close = getattr(rest, "aclose", None)
        if close is not None:
            await close()


def _to_json(obj: object) -> str:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            return json.dumps(dataclasses.asdict(obj), default=str, indent=2)
        except TypeError:
            return repr(obj)
    if hasattr(obj, "model_dump"):
        try:
            return json.dumps(obj.model_dump(), default=str, indent=2)
        except TypeError:
            return repr(obj)
    try:
        return json.dumps(obj, default=str, indent=2)
    except TypeError:
        return repr(obj)


if __name__ == "__main__":
    app()
