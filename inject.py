"""Night 2: build the broker's statement and plant breaks in it.

Reads the internal blotter, writes three files:

    data/broker_statement.csv   what the broker sent us (with breaks and mess)
    data/ground_truth.csv       every economic break we planted, with its cash effect
    data/noise_log.csv          every piece of formatting mess we planted

The engine (nights 3 to 6) only ever sees the blotter and the statement.
The ground truth is the answer key the tests grade it against.

Run:  python3 inject.py            (uses the seed in config.py)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import config
from calendars import add_settlement_days
from common import signed_cash
from normalize import load_internal

# The broker does not use our column names or our side codes. Real statements
# never do, and mapping them back is the first job of normalization (night 3).
BROKER_COLUMNS = {
    "trade_id": "ref",
    "symbol": "sym",
    "side": "bs",
    "quantity": "qty",
    "price": "px",
    "currency": "ccy",
    "trade_date": "trade_dt",
    "settle_date": "settle_dt",
    "fees": "comm",
    "account": "acct",
    "broker": "broker",
}
SIDE_CODES = {"BUY": "B", "SELL": "S"}


def tick_and_lot(row) -> tuple[float, int]:
    _, tick, lot = config.MARKETS[row["market"]]["symbols"][row["symbol"]]
    return tick, lot


def cash(row) -> float:
    return signed_cash(row["side"], row["quantity"], row["price"], row["fees"])


TRUTH_COLUMNS = ["trade_id", "break_type", "field", "internal_value", "broker_value", "currency", "cash_diff"]
NOISE_COLUMNS = ["trade_id", "noise_type"]


def inject(internal: pd.DataFrame, seed: int = config.SEED, break_counts: dict | None = None,
           noise_counts: dict | None = None, date_format_noise: float | None = None):
    """Return (broker_statement, ground_truth, noise_log).

    The counts default to config.py. Tests override them, for example to ask
    for a statement with noise but no breaks at all.
    """
    break_counts = config.BREAK_COUNTS if break_counts is None else break_counts
    noise_counts = {**{k: 0 for k in config.NOISE_COUNTS}, **(config.NOISE_COUNTS if noise_counts is None else noise_counts)}
    date_format_noise = config.DATE_FORMAT_NOISE if date_format_noise is None else date_format_noise
    # A separate random stream from generate.py, so changing the break counts
    # never changes which trades exist.
    rng = np.random.default_rng([seed, 2])

    broker = internal.copy()
    truth: list[dict] = []
    noise: list[dict] = []

    # Pick the trades to break. No replacement: one economic break per trade.
    n_breaks = sum(break_counts.values())
    chosen = rng.choice(len(broker), size=n_breaks, replace=False)
    plan = [t for t, n in break_counts.items() for _ in range(n)]

    to_drop: list[int] = []
    to_duplicate: list[int] = []

    for i, break_type in zip(chosen, plan):
        ours = internal.iloc[i]
        theirs = ours.copy()
        field = old = new = None

        if break_type == "PRICE":
            tick, _ = tick_and_lot(ours)
            ticks = int(rng.integers(1, 21)) * (1 if rng.random() < 0.5 else -1)
            field, old = "price", ours["price"]
            new = round(ours["price"] + ticks * tick, 2)
            if new <= 0:  # never produce a zero or negative price
                new = round(ours["price"] + abs(ticks) * tick, 2)
            theirs["price"] = new

        elif break_type == "QUANTITY":
            _, lot = tick_and_lot(ours)
            unit = lot if lot > 1 else 100  # US mistakes tend to be round lots too
            delta = int(rng.integers(1, 6)) * unit * (1 if rng.random() < 0.5 else -1)
            field, old = "quantity", int(ours["quantity"])
            new = old + delta
            if new <= 0:
                new = old + abs(delta)
            theirs["quantity"] = new

        elif break_type == "SIDE":
            field, old = "side", ours["side"]
            new = "SELL" if old == "BUY" else "BUY"
            theirs["side"] = new

        elif break_type == "FEE":
            field, old = "fees", ours["fees"]
            factor = 1 + rng.uniform(0.05, 0.50) * (1 if rng.random() < 0.5 else -1)
            new = round(old * factor, 2)
            if new == old:  # tiny fees can round back to the same cent
                new = round(old + 0.01, 2)
            theirs["fees"] = new

        elif break_type == "SETTLE_DATE":
            field, old = "settle_date", ours["settle_date"]
            new = add_settlement_days(ours["market"], old, 1 if rng.random() < 0.5 else -1)
            if new < ours["trade_date"]:  # nobody books settlement before the trade
                new = add_settlement_days(ours["market"], old, 1)
            theirs["settle_date"] = new

        elif break_type == "MISSING":
            field, old, new = "(whole trade)", "present", "absent"
            to_drop.append(i)

        elif break_type == "DUPLICATE":
            field, old, new = "(whole trade)", "1 row", "2 rows"
            to_duplicate.append(i)

        # The cash effect of the break: what our books say minus what theirs say.
        our_cash = cash(ours)
        if break_type == "MISSING":
            their_cash = 0.0             # broker thinks no cash moves at all
        elif break_type == "DUPLICATE":
            their_cash = 2 * our_cash    # broker thinks it moves twice
        else:
            their_cash = cash(theirs)

        broker.iloc[i] = theirs
        truth.append({
            "trade_id": ours["trade_id"],
            "break_type": break_type,
            "field": field,
            "internal_value": old,
            "broker_value": new,
            "currency": ours["currency"],
            "cash_diff": round(our_cash - their_cash, 2),
        })

    # Apply the row-level breaks.
    duplicates = broker.iloc[to_duplicate]
    broker = pd.concat([broker.drop(broker.index[to_drop]), duplicates], ignore_index=True)

    # ---- Noise: formatting mess, applied to the broker's copy only ----------
    broken_ids = {t["trade_id"] for t in truth}

    def pick(n: int, clean_only: bool = False) -> np.ndarray:
        rows = np.arange(len(broker))
        if clean_only:
            rows = rows[~broker["trade_id"].isin(broken_ids).to_numpy()]
        return rng.choice(rows, size=n, replace=False)

    broker["symbol"] = broker["symbol"].astype(object)
    for r in pick(noise_counts["SYMBOL_CASE"]):
        noise.append({"trade_id": broker.at[r, "trade_id"], "noise_type": "SYMBOL_CASE"})
        broker.at[r, "symbol"] = broker.at[r, "symbol"].lower()

    for r in pick(noise_counts["WHITESPACE"]):
        noise.append({"trade_id": broker.at[r, "trade_id"], "noise_type": "WHITESPACE"})
        pad = [" ", "  ", "\t"][int(rng.integers(3))]
        broker.at[r, "symbol"] = pad + broker.at[r, "symbol"] + pad

    # Dates become strings, some of them in a non-ISO format.
    formats = config.BROKER_DATE_FORMATS
    for r in range(len(broker)):
        fmt = formats[0]
        if rng.random() < date_format_noise:
            fmt = formats[int(rng.integers(1, len(formats)))]
            noise.append({"trade_id": broker.at[r, "trade_id"], "noise_type": "DATE_FORMAT"})
        for col in ("trade_date", "settle_date"):
            broker.at[r, col] = broker.at[r, col].strftime(fmt)

    # Blank trade references go last, and only on otherwise clean trades, so
    # the fallback match on night 6 is never ambiguous.
    for r in pick(noise_counts["MISSING_ID"], clean_only=True):
        noise.append({"trade_id": broker.at[r, "trade_id"], "noise_type": "MISSING_ID"})
        broker.at[r, "trade_id"] = ""

    # Finally, make it look like their file, not ours: their columns, their
    # side codes, their row order.
    broker["side"] = broker["side"].map(SIDE_CODES)
    broker = broker[list(BROKER_COLUMNS)].rename(columns=BROKER_COLUMNS)
    broker = broker.iloc[rng.permutation(len(broker))].reset_index(drop=True)

    return broker, pd.DataFrame(truth, columns=TRUTH_COLUMNS), pd.DataFrame(noise, columns=NOISE_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the broker statement with planted breaks.")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--outdir", default="data")
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker, truth, noise = inject(internal, args.seed)

    out = Path(args.outdir)
    broker.to_csv(out / "broker_statement.csv", index=False)
    truth.to_csv(out / "ground_truth.csv", index=False)
    noise.to_csv(out / "noise_log.csv", index=False)

    print(f"internal rows: {len(internal)}   broker rows: {len(broker)}")
    print()
    print("economic breaks planted:")
    # Grouped by currency as well as type: HKD and USD are never added together.
    print(truth.groupby(["break_type", "currency"])["cash_diff"]
          .agg(count="size", cash_diff="sum").round(2).to_string())
    print()
    print("noise planted:", noise["noise_type"].value_counts().to_dict())
    print()
    print("a few rows of the broker's file:")
    print(broker.head(6).to_string(index=False))


if __name__ == "__main__":
    main()
