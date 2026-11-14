"""Night 1: generate the clean internal blotter.

Run:  python3 generate.py            (uses the seed in config.py)
      python3 generate.py --seed 7   (a different, equally reproducible day)
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import config
from calendars import expected_settle_date, trading_days

COLUMNS = [
    "trade_id", "timestamp", "trade_date", "settle_date", "symbol", "market",
    "side", "quantity", "price", "currency", "venue", "account", "broker", "fees",
]


def random_time(rng: np.random.Generator, sessions) -> timedelta:
    """A random second inside the trading sessions, as an offset from midnight."""
    spans = []
    for start, end in sessions:
        s = start.hour * 3600 + start.minute * 60
        e = end.hour * 3600 + end.minute * 60
        spans.append((s, e))
    lengths = np.array([e - s for s, e in spans], dtype=float)
    i = rng.choice(len(spans), p=lengths / lengths.sum())  # longer session, more trades
    s, e = spans[i]
    return timedelta(seconds=int(rng.integers(s, e)))


def make_trade(rng: np.random.Generator, days: dict[str, list[date]]) -> dict:
    market = "US" if rng.random() < config.US_SHARE else "HK"
    m = config.MARKETS[market]

    symbol = str(rng.choice(list(m["symbols"])))
    ref_price, tick, lot = m["symbols"][symbol]

    # Price: reference price nudged by noise, then snapped to the tick grid.
    raw = ref_price * (1 + rng.normal(0, config.PRICE_VOL))
    price = round(round(raw / tick) * tick, 2)

    quantity = int(rng.integers(1, m["max_lots"] + 1)) * lot
    # A trade can only happen on a day its own market is open.
    market_days = days[market]
    trade_date = market_days[int(rng.integers(len(market_days)))]

    # The timestamp is in the market's own time zone. trade_date is the local
    # date there, which is what the exchange and the broker both use.
    local = datetime.combine(trade_date, datetime.min.time(), ZoneInfo(m["timezone"]))
    local += random_time(rng, m["sessions"])

    notional = quantity * price
    return {
        "timestamp": local,
        "trade_date": trade_date,
        "settle_date": expected_settle_date(market, trade_date),
        "symbol": symbol,
        "market": market,
        "side": "BUY" if rng.random() < 0.5 else "SELL",
        "quantity": quantity,
        "price": price,
        "currency": m["currency"],
        "venue": str(rng.choice(m["venues"])),
        "account": str(rng.choice(config.ACCOUNTS)),
        "broker": str(rng.choice(config.BROKERS)),
        "fees": round(notional * m["fee_bps"] / 10_000, 2),
    }


def generate(seed: int = config.SEED, n: int = config.N_TRADES) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = {m: trading_days(m, *config.TRADE_WINDOW) for m in config.MARKETS}

    # No two genuine trades may share symbol, side, quantity and trade date.
    # That is the key the fuzzy matcher falls back on (night 6), and it also
    # means any exact repeat on the broker side must be an injected duplicate.
    trades, seen = [], set()
    while len(trades) < n:
        t = make_trade(rng, days)
        key = (t["symbol"], t["side"], t["quantity"], t["trade_date"])
        if key in seen:
            continue
        seen.add(key)
        trades.append(t)

    # Number the trades in the order they actually happened across both markets.
    trades.sort(key=lambda t: t["timestamp"].astimezone(ZoneInfo("UTC")))
    for i, t in enumerate(trades, start=1):
        t["trade_id"] = f"T{i:06d}"
        t["timestamp"] = t["timestamp"].isoformat()

    return pd.DataFrame(trades)[COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the internal blotter.")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--n", type=int, default=config.N_TRADES)
    parser.add_argument("--out", default="data/internal_blotter.csv")
    args = parser.parse_args()

    df = generate(args.seed, args.n)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    notional = df["quantity"] * df["price"]
    print(f"wrote {len(df)} trades to {out} (seed {args.seed})")
    print(df.head(8).to_string(index=False))
    print()
    print("trades by market:", df["market"].value_counts().to_dict())
    print("notional by currency:", notional.groupby(df["currency"]).sum().round(2).to_dict())


if __name__ == "__main__":
    main()
