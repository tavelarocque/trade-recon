"""Night 5: settlement checks on top of the break list.

Three questions, answered from the calendar and never from the answer key:

    1. Is our own book right?  audit_internal() recomputes the settlement
       date of every trade on our blotter and lists any that disagree.
    2. When a settlement date break exists, who is wrong?  The side whose
       date differs from the calendar's.
    3. How urgent is each break?  A break on a trade that settles today or
       on the next settlement day must be fixed before anything else.

Run:  python3 settlement.py
      python3 settlement.py --as-of 2026-11-12
"""
from __future__ import annotations

import argparse
from datetime import date, datetime

import pandas as pd

import config
from calendars import add_settlement_days, expected_settle_date, is_settlement_day
from classify import classify
from match import match_all
from normalize import load_broker, load_internal

MARKET_OF_CURRENCY = {m["currency"]: name for name, m in config.MARKETS.items()}


def audit_internal(internal: pd.DataFrame) -> pd.DataFrame:
    """Trades on our own blotter whose settle date is not what the calendar says."""
    expected = [expected_settle_date(m, t) for m, t in zip(internal["market"], internal["trade_date"])]
    out = internal.assign(expected_settle_date=expected)
    return out[out["settle_date"] != out["expected_settle_date"]]


def settle_status(market: str, settle: date, as_of: date) -> str:
    """Where a trade stands relative to the day the report is run."""
    if settle < as_of:
        return "PAST_SETTLEMENT"   # should already have settled: check for a fail
    if settle == as_of:
        return "DUE_TODAY"
    next_day = add_settlement_days(market, as_of, 1)
    if settle == next_day:
        return "DUE_NEXT_DAY"
    return "LATER"


def annotate(breaks: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Add expected_settle_date, wrong_side and settle_status to each break."""
    out = breaks.copy()
    markets = out["currency"].map(MARKET_OF_CURRENCY)
    out["expected_settle_date"] = [expected_settle_date(m, t) for m, t in zip(markets, out["trade_date"])]

    wrong = []
    for _, b in out.iterrows():
        if b["break_type"] != "SETTLE_DATE":
            wrong.append("")
        elif b["internal_value"] == b["expected_settle_date"]:
            wrong.append("broker")
        elif b["broker_value"] == b["expected_settle_date"]:
            wrong.append("us")
        else:
            wrong.append("both")
    out["wrong_side"] = wrong

    out["settle_status"] = [settle_status(m, s, as_of) for m, s in zip(markets, out["expected_settle_date"])]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Settlement checks.")
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--broker", default="data/broker_statement.csv")
    parser.add_argument("--as-of", default=None, help="report date, YYYY-MM-DD (default: last trade date)")
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker = load_broker(args.broker)
    as_of = (datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of
             else internal["trade_date"].max())

    wrong_ours = audit_internal(internal)
    print(f"our own blotter: {len(wrong_ours)} of {len(internal)} trades have a settle date "
          f"that disagrees with the calendar")
    if len(wrong_ours):
        print(wrong_ours[["trade_id", "market", "trade_date", "settle_date", "expected_settle_date"]].to_string(index=False))

    breaks = annotate(classify(match_all(internal, broker)), as_of)

    print()
    print("settlement date breaks, and which side the calendar says is wrong:")
    sd = breaks[breaks["break_type"] == "SETTLE_DATE"]
    print(sd[["trade_id", "symbol", "trade_date", "internal_value", "broker_value",
              "expected_settle_date", "wrong_side", "impact_usd"]].to_string(index=False))

    print()
    open_in = [m for m in config.MARKETS if is_settlement_day(m, as_of)]
    print(f"all breaks by urgency, as of {as_of} (settlement day in: {', '.join(open_in) or 'neither market'}):")
    order = ["PAST_SETTLEMENT", "DUE_TODAY", "DUE_NEXT_DAY", "LATER"]
    summary = breaks.groupby("settle_status").agg(breaks=("impact_usd", "size"), impact_usd=("impact_usd", "sum"))
    print(summary.reindex([o for o in order if o in summary.index]).round(2).to_string())


if __name__ == "__main__":
    main()
