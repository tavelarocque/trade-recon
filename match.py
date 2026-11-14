"""Nights 3 and 6: pair up the two sides.

Every row on either side ends up in exactly one of four buckets:

    matched             one of ours paired with one of theirs
    duplicates          extra broker rows repeating an ID already paired
    unmatched_internal  ours, with no partner
    unmatched_broker    theirs, with no partner

Matching runs in two passes.

    Pass 1, by ID (night 3).  Exact match on trade_id.
    Pass 2, fallback (night 6).  For rows still unpaired, match on symbol,
    side, quantity and trade date, and only when exactly one candidate
    exists on each side. If two could fit, the engine pairs neither. A wrong
    pairing hides a real break and invents a false one, so it is better to
    hand an analyst two unpaired rows than one confident mistake.

Only what is still unmatched after both passes is a missing trade.

Run:  python3 match.py
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from normalize import COMPARE_FIELDS, load_broker, load_internal

FALLBACK_KEY = ["symbol", "side", "quantity", "trade_date"]


@dataclass
class MatchResult:
    matched: pd.DataFrame             # trade_id, broker_row, match_method, <field>_int, <field>_brk
    duplicates: pd.DataFrame          # broker rows
    unmatched_internal: pd.DataFrame  # internal rows
    unmatched_broker: pd.DataFrame    # broker rows

    def counts(self) -> dict:
        return {
            "matched": len(self.matched),
            "of which by fallback": int((self.matched["match_method"] == "fallback").sum()),
            "duplicates": len(self.duplicates),
            "unmatched_internal": len(self.unmatched_internal),
            "unmatched_broker": len(self.unmatched_broker),
        }


def _check_books(result: MatchResult, internal: pd.DataFrame, broker: pd.DataFrame) -> None:
    """No row on either side may be lost or counted twice."""
    assert len(result.matched) + len(result.unmatched_internal) == len(internal), "internal rows do not add up"
    assert (len(result.matched) + len(result.duplicates) + len(result.unmatched_broker)
            == len(broker)), "broker rows do not add up"


def match_by_id(internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    has_id = broker["trade_id"].notna()
    with_id = broker[has_id]

    # The first broker row for each ID is the candidate partner. Any later row
    # with the same ID is a duplicate: the broker is showing one trade twice.
    is_repeat = with_id.duplicated("trade_id", keep="first")
    first = with_id[~is_repeat]
    duplicates = with_id[is_repeat]

    # Inner join: keep only IDs present on both sides, side by side.
    matched = internal[["trade_id"] + COMPARE_FIELDS].merge(
        first[["trade_id", "broker_row"] + COMPARE_FIELDS],
        on="trade_id", how="inner", suffixes=("_int", "_brk"),
        validate="one_to_one",  # pandas raises if either side repeats an ID
    )
    matched["match_method"] = "id"

    paired = set(matched["trade_id"])
    unmatched_internal = internal[~internal["trade_id"].isin(paired)]
    # Theirs without a partner: blank reference, or an ID we do not recognise.
    unmatched_broker = pd.concat([broker[~has_id], first[~first["trade_id"].isin(paired)]])

    result = MatchResult(matched, duplicates, unmatched_internal, unmatched_broker)
    _check_books(result, internal, broker)
    return result


def match_fallback(result: MatchResult, internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """Second pass: pair leftovers on symbol, side, quantity and trade date."""
    ours, theirs = result.unmatched_internal, result.unmatched_broker
    if ours.empty or theirs.empty:
        return result

    # Only keys that occur exactly once on each side are safe to pair on.
    ours_unique = ours[~ours.duplicated(FALLBACK_KEY, keep=False)]
    theirs_unique = theirs[~theirs.duplicated(FALLBACK_KEY, keep=False)]

    rest = [f for f in COMPARE_FIELDS if f not in FALLBACK_KEY]
    pairs = ours_unique[["trade_id"] + COMPARE_FIELDS].merge(
        theirs_unique[["broker_row"] + COMPARE_FIELDS],
        on=FALLBACK_KEY, how="inner", suffixes=("_int", "_brk"), validate="one_to_one",
    )
    if pairs.empty:
        return result

    # The key fields agree by construction, so both sides carry the same value.
    for f in FALLBACK_KEY:
        pairs[f + "_int"] = pairs[f]
        pairs[f + "_brk"] = pairs[f]
    pairs = pairs.drop(columns=FALLBACK_KEY)
    pairs["match_method"] = "fallback"
    assert all(f + "_int" in pairs and f + "_brk" in pairs for f in rest)

    new = MatchResult(
        matched=pd.concat([result.matched, pairs[result.matched.columns]], ignore_index=True),
        duplicates=result.duplicates,
        unmatched_internal=ours[~ours["trade_id"].isin(pairs["trade_id"])],
        unmatched_broker=theirs[~theirs["broker_row"].isin(pairs["broker_row"])],
    )
    _check_books(new, internal, broker)
    return new


def match_all(internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """Both passes. This is what the rest of the engine calls."""
    return match_fallback(match_by_id(internal, broker), internal, broker)


def main() -> None:
    parser = argparse.ArgumentParser(description="Match the blotter to the broker statement.")
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--broker", default="data/broker_statement.csv")
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker = load_broker(args.broker)

    by_id = match_by_id(internal, broker)
    result = match_fallback(by_id, internal, broker)

    print(f"internal rows: {len(internal)}   broker rows: {len(broker)}")
    print()
    print(f"{'':<24}{'ID only':>10}{'ID + fallback':>16}")
    for (name, a), b in zip(by_id.counts().items(), result.counts().values()):
        print(f"  {name:<22}{a:>10}{b:>16}")
    print()
    print("paired by the fallback (broker gave no usable reference):")
    fb = result.matched[result.matched["match_method"] == "fallback"]
    print(fb[["trade_id", "broker_row", "symbol_int", "side_int", "quantity_int", "trade_date_int"]]
          .rename(columns=lambda c: c.replace("_int", "")).to_string(index=False))
    print()
    print("still unmatched, ours (these are the real missing trades):")
    print(result.unmatched_internal[["trade_id", "symbol", "side", "quantity", "trade_date"]].to_string(index=False))


if __name__ == "__main__":
    main()
