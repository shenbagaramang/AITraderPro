"""Bridge live TradingView chart data into AITraderPro's analysis endpoints.

TradingView Desktop has no free historical-data API of its own, and
AITraderPro's /analysis endpoints deliberately take candles inline rather
than pretending to have a data source they don't (see candle_service.py).
This script is the missing middle: it reads OHLCV bars in the shape the
TradingView MCP's data_get_ohlcv tool returns (unix-second "time" field)
and runs them through AITraderPro's technical agent and decision engine.

Usage:
    python scripts/tv_bridge_analyze.py --symbol RELIANCE bars.json
    cat bars.json | python scripts/tv_bridge_analyze.py --symbol RELIANCE

bars.json is a JSON array of {time, open, high, low, close, volume} — the
native shape returned by the TradingView MCP's data_get_ohlcv tool.

Env vars (same convention as mcp_server/server.py):
    AITRADERPRO_URL       default http://localhost:8000/api/v1
    AITRADERPRO_EMAIL     required
    AITRADERPRO_PASSWORD  required
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

import httpx

BASE_URL = os.environ.get("AITRADERPRO_URL", "http://localhost:8000/api/v1")


def _login(client: httpx.Client) -> dict[str, str]:
    email = os.environ.get("AITRADERPRO_EMAIL")
    password = os.environ.get("AITRADERPRO_PASSWORD")
    if not email or not password:
        raise SystemExit("Set AITRADERPRO_EMAIL and AITRADERPRO_PASSWORD")
    resp = client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()


def _to_candles(tv_bars: list[dict]) -> list[dict]:
    """TradingView's {time, open, high, low, close, volume} -> AITraderPro's CandleRow shape."""
    candles = []
    for bar in tv_bars:
        candles.append(
            {
                "timestamp": datetime.fromtimestamp(bar["time"], tz=UTC).isoformat(),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        )
    return candles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bars_file", nargs="?", help="Path to a TradingView-shaped bars JSON file (default: stdin)")
    parser.add_argument("--symbol", required=True, help="Symbol, e.g. RELIANCE")
    parser.add_argument("--equity", type=float, default=100000.0, help="Account equity for --decide sizing")
    parser.add_argument("--lot-size", type=int, default=1)
    parser.add_argument("--skip-decide", action="store_true", help="Only run the technical agent, skip the decision engine")
    args = parser.parse_args()

    raw = open(args.bars_file).read() if args.bars_file else sys.stdin.read()
    tv_bars = json.loads(raw)
    candles = _to_candles(tv_bars)
    print(f"Loaded {len(candles)} bars for {args.symbol} from TradingView", file=sys.stderr)

    with httpx.Client(timeout=30.0) as client:
        tokens = _login(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        technical = client.post(
            f"{BASE_URL}/analysis/technical",
            json={"symbol": args.symbol, "candles": candles},
            headers=headers,
        )
        technical.raise_for_status()
        view = technical.json()

        print(f"\n=== Technical view: {view['symbol']} ===")
        print(f"Bias: {view['bias']}  Conviction: {view['conviction']}  Score: {view['score']:.2f}  Agreement: {view['agreement']:.0%}")
        print(f"Regime: {view['regime']}  Suggested action: {view['action']}")
        if view["rationale"]:
            print("Rationale:")
            for line in view["rationale"]:
                print(f"  - {line}")
        if view["conflicts"]:
            print("Conflicts:")
            for line in view["conflicts"]:
                print(f"  - {line}")
        print("Signals:")
        for s in view["signals"]:
            print(f"  {s['scanner']:<12} {s['direction']:<8} strength={s['strength']:.2f}  {s['reason']}")

        if args.skip_decide:
            return

        decide = client.post(
            f"{BASE_URL}/analysis/decide",
            json={
                "symbol": args.symbol,
                "candles": candles,
                "equity": args.equity,
                "lot_size": args.lot_size,
            },
            headers=headers,
        )
        decide.raise_for_status()
        decision = decide.json()

        print(f"\n=== Decision engine: {decision['outcome'].upper()} ===")
        print(f"Action: {decision['action']}  Confidence: {decision['confidence']:.0%}")
        if decision["quantity"]:
            print(f"Quantity: {decision['quantity']}  Entry: {decision['entry']}  Stop: {decision['stop_loss']}  Target: {decision['target']}")
        if decision["reasons"]:
            print("Reasons:")
            for line in decision["reasons"]:
                print(f"  - {line}")
        if decision["vetoes"]:
            print("Vetoes:")
            for line in decision["vetoes"]:
                print(f"  - {line}")
        print("Agent votes:")
        for agent, vote in decision["agent_votes"].items():
            print(f"  {agent}: {vote}")


if __name__ == "__main__":
    main()
