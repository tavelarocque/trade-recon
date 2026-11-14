"""Night 3, part 1: read both files into one common shape.

After this module, both sides have the same column names, the same types and
the same spellings, so any difference that remains is a real difference.

The rule of thumb: read the broker's file as text first, clean it, and only
then convert to numbers and dates. If you let pandas (or Excel) guess the
types on the way in, 20261117 becomes the number twenty million and a blank
reference becomes NaN before you ever get to look at it.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

import config

# The fields both sides must agree on, in our naming.
COMPARE_FIELDS = ["symbol", "side", "quantity", "price", "currency",
                  "trade_date", "settle_date", "fees", "account", "broker"]

# Broker column name -> our column name.
BROKER_TO_OURS = {
    "ref": "trade_id", "sym": "symbol", "bs": "side", "qty": "quantity",
    "px": "price", "ccy": "currency", "trade_dt": "trade_date",
    "settle_dt": "settle_date", "comm": "fees", "acct": "account",
    "broker": "broker",
}
SIDE_FROM_CODE = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}


def parse_date(text: str) -> date:
    """Parse a date written in any of the known formats, or fail loudly.

    Failing loudly matters. A date we cannot read must stop the run, not
    quietly turn into a blank that later looks like a settlement break.
    """
    for fmt in config.BROKER_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format: {text!r}")


def load_internal(path: str | Path) -> pd.DataFrame:
    """Our own blotter. It is already clean, so this only fixes the types."""
    df = pd.read_csv(path)
    for col in ("trade_date", "settle_date"):
        df[col] = pd.to_datetime(df[col]).dt.date
    if not df["trade_id"].is_unique:
        raise ValueError("internal blotter has repeated trade_ids")
    return df


def load_broker(path: str | Path) -> pd.DataFrame:
    """The broker's statement, cleaned into our shape.

    Every row keeps a `broker_row` number (its line in their file) so that any
    break can be traced back to the exact line we would quote to the broker.
    """
    # dtype=str: nothing is guessed. keep_default_na=False: blanks stay "".
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)

    missing = set(BROKER_TO_OURS) - set(raw.columns)
    if missing:
        raise ValueError(f"broker file is missing columns: {sorted(missing)}")

    df = raw.rename(columns=BROKER_TO_OURS)[list(BROKER_TO_OURS.values())]
    df.insert(0, "broker_row", range(2, len(df) + 2))  # line 1 is the header

    # 1. Whitespace: strip every text field, not just the one we saw mess in.
    for col in BROKER_TO_OURS.values():
        df[col] = df[col].str.strip()

    # 2. Case: identifiers are compared in upper case.
    for col in ("trade_id", "symbol", "side", "currency", "account", "broker"):
        df[col] = df[col].str.upper()

    # 3. Codes: B and S become BUY and SELL. An unknown code stops the run.
    unknown = set(df["side"]) - set(SIDE_FROM_CODE)
    if unknown:
        raise ValueError(f"unknown side codes in broker file: {sorted(unknown)}")
    df["side"] = df["side"].map(SIDE_FROM_CODE)

    # 4. Dates: one explicit parser, three known formats.
    for col in ("trade_date", "settle_date"):
        df[col] = df[col].map(parse_date)

    # 5. Numbers: converted last, and an unreadable number stops the run.
    df["quantity"] = pd.to_numeric(df["quantity"]).astype(int)
    df["price"] = pd.to_numeric(df["price"]).astype(float)
    df["fees"] = pd.to_numeric(df["fees"]).astype(float)

    # 6. A blank reference is a missing value, said honestly.
    df["trade_id"] = df["trade_id"].where(df["trade_id"] != "", pd.NA)

    return df
