"""Pair up the two sides.

Every broker line and every trade of ours ends up in exactly one bucket:

    matched             one of ours paired with one broker line, or with
                        several fills folded into one
    duplicates          extra broker lines repeating a trade already paired
    unmatched_internal  ours, with no partner
    unmatched_broker    theirs, with no partner

Matching runs in four steps.

    1. Fold fills.  When several broker lines carry the same reference and
       their quantities add up to ours, they are fills of one trade. They
       are folded into one line: summed quantity, average price weighted by
       quantity, summed fees. Lines that are exact copies of each other are
       not fills, they are duplicates.
    2. By ID.  Exact match on trade_id.
    3. Fallback, one to one.  For rows still unpaired, match on symbol,
       side, quantity and trade date, only when exactly one candidate
       exists on each side.
    4. Fallback, one to many.  For a trade of ours still unpaired, if it is
       the only one of ours left for its symbol, side and trade date, and
       the broker's unreferenced lines for that same symbol, side and date
       add up to its quantity, they are its fills.

Every fallback refuses to guess. If two candidates could fit, the engine
pairs neither: a wrong pairing hides a real break and invents a false one.

Only what is still unmatched after all four steps is a missing trade.

Run:  python3 match.py
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

from normalize import COMPARE_FIELDS, load_broker, load_internal

FALLBACK_KEY = ["symbol", "side", "quantity", "trade_date"]
CELL = ["symbol", "side", "trade_date"]
# Fills of one trade may differ in quantity, price and fees. On everything
# else they must agree, or they are not folded.
MUST_AGREE = [f for f in COMPARE_FIELDS if f not in ("quantity", "price", "fees")]
LINE_COLUMNS = ["broker_row", "broker_rows", "fills"]


@dataclass
class MatchResult:
    matched: pd.DataFrame             # trade_id, broker_row, broker_rows, fills, match_method, <field>_int, <field>_brk
    duplicates: pd.DataFrame          # broker lines
    unmatched_internal: pd.DataFrame  # internal rows
    unmatched_broker: pd.DataFrame    # broker lines

    def counts(self) -> dict:
        m = self.matched
        return {
            "matched": len(m),
            "of which by fallback": int((m["match_method"] == "fallback").sum()),
            "of which from several fills": int((m["fills"] > 1).sum()),
            "duplicates": len(self.duplicates),
            "unmatched_internal": len(self.unmatched_internal),
            "unmatched_broker": len(self.unmatched_broker),
        }


def with_line_columns(broker: pd.DataFrame) -> pd.DataFrame:
    """Every broker line starts as one fill that knows its own line number."""
    if "fills" in broker.columns:
        return broker
    out = broker.copy()
    out["fills"] = 1
    out["broker_rows"] = out["broker_row"].astype(str)
    return out


def fold(lines: pd.DataFrame) -> dict | None:
    """Fold several fills into one line, or None if they disagree on a field
    that fills of the same trade must share."""
    if any(lines[f].nunique() != 1 for f in MUST_AGREE):
        return None
    qty = int(lines["quantity"].sum())
    out = lines.iloc[0].to_dict()
    out["quantity"] = qty
    # Average price weighted by quantity: total money divided by total shares.
    out["price"] = round(float((lines["quantity"] * lines["price"]).sum()) / qty, 6)
    out["fees"] = round(float(lines["fees"].sum()), 2)
    out["fills"] = int(lines["fills"].sum())
    out["broker_row"] = int(lines["broker_row"].min())
    out["broker_rows"] = "+".join(str(r) for r in sorted(lines["broker_row"]))
    return out


def fold_fills(internal: pd.DataFrame, broker: pd.DataFrame) -> pd.DataFrame:
    """Step 1: fold broker lines that share a reference into one line per trade."""
    broker = with_line_columns(broker)
    our_qty = dict(zip(internal["trade_id"], internal["quantity"]))
    has_id = broker["trade_id"].notna()
    keep = [broker[~has_id]]
    folded = []
    for tid, lines in broker[has_id].groupby("trade_id", sort=False):
        if len(lines) == 1 or tid not in our_qty:
            keep.append(lines)
            continue
        adds_up = int(lines["quantity"].sum()) == int(our_qty[tid])
        copies = len(lines[["quantity", "price", "fees"]].drop_duplicates()) == 1
        if copies and not adds_up:
            keep.append(lines)        # the same line repeated: duplicates, handled later
            continue
        one = fold(lines)             # fills, complete or partial
        if one is None:
            keep.append(lines)
        else:
            folded.append(one)
    if folded:
        keep.append(pd.DataFrame(folded, columns=broker.columns))
    return pd.concat(keep, ignore_index=True)


def _check_books(result: MatchResult, internal: pd.DataFrame, broker: pd.DataFrame) -> None:
    """No trade of ours and no broker line may be lost or counted twice."""
    assert len(result.matched) + len(result.unmatched_internal) == len(internal), "internal rows do not add up"
    lines = (int(result.matched["fills"].sum()) + int(result.duplicates["fills"].sum())
             + int(result.unmatched_broker["fills"].sum()))
    assert lines == int(broker["fills"].sum()), "broker lines do not add up"


def match_by_id(internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """Step 2: exact match on trade_id."""
    broker = with_line_columns(broker)
    has_id = broker["trade_id"].notna()
    with_id = broker[has_id]

    # The first broker line for each ID is the candidate partner. Any later
    # line with the same ID is a duplicate: the broker shows one trade twice.
    is_repeat = with_id.duplicated("trade_id", keep="first")
    first = with_id[~is_repeat]
    duplicates = with_id[is_repeat]

    # Inner join: keep only IDs present on both sides, side by side.
    matched = internal[["trade_id"] + COMPARE_FIELDS].merge(
        first[["trade_id"] + LINE_COLUMNS + COMPARE_FIELDS],
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


def _add_pairs(result: MatchResult, pairs: pd.DataFrame, used_rows: set,
               internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    pairs = pairs.copy()
    pairs["match_method"] = "fallback"
    new = MatchResult(
        matched=pd.concat([result.matched, pairs[result.matched.columns]], ignore_index=True),
        duplicates=result.duplicates,
        unmatched_internal=result.unmatched_internal[~result.unmatched_internal["trade_id"].isin(pairs["trade_id"])],
        unmatched_broker=result.unmatched_broker[~result.unmatched_broker["broker_row"].isin(used_rows)],
    )
    _check_books(new, internal, broker)
    return new


def match_fallback(result: MatchResult, internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """Step 3: pair leftovers one to one on symbol, side, quantity and trade date."""
    broker = with_line_columns(broker)
    ours, theirs = result.unmatched_internal, result.unmatched_broker
    if ours.empty or theirs.empty:
        return result

    # Only keys that occur exactly once on each side are safe to pair on.
    ours_unique = ours[~ours.duplicated(FALLBACK_KEY, keep=False)]
    theirs_unique = theirs[~theirs.duplicated(FALLBACK_KEY, keep=False)]

    pairs = ours_unique[["trade_id"] + COMPARE_FIELDS].merge(
        theirs_unique[LINE_COLUMNS + COMPARE_FIELDS],
        on=FALLBACK_KEY, how="inner", suffixes=("_int", "_brk"), validate="one_to_one",
    )
    if pairs.empty:
        return result

    # The key fields agree by construction, so both sides carry the same value.
    for f in FALLBACK_KEY:
        pairs[f + "_int"] = pairs[f]
        pairs[f + "_brk"] = pairs[f]
    pairs = pairs.drop(columns=FALLBACK_KEY)
    return _add_pairs(result, pairs, set(pairs["broker_row"]), internal, broker)


def match_fallback_fills(result: MatchResult, internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """Step 4: pair one of ours with several unreferenced broker fills."""
    broker = with_line_columns(broker)
    ours, theirs = result.unmatched_internal, result.unmatched_broker
    loose = theirs[theirs["trade_id"].isna()]
    if ours.empty or len(loose) < 2:
        return result

    # A trade of ours qualifies only if it is alone in its symbol, side and date.
    alone = ours[~ours.duplicated(CELL, keep=False)]
    pairs, used = [], set()
    for key, lines in loose.groupby(CELL, sort=False):
        if len(lines) < 2:
            continue
        mine = alone[(alone["symbol"] == key[0]) & (alone["side"] == key[1]) & (alone["trade_date"] == key[2])]
        if len(mine) != 1 or int(lines["quantity"].sum()) != int(mine.iloc[0]["quantity"]):
            continue                      # nothing fits, or it does not add up: leave it alone
        one = fold(lines)
        if one is None:
            continue
        m = mine.iloc[0]
        row = {"trade_id": m["trade_id"], **{c: one[c] for c in LINE_COLUMNS}}
        for f in COMPARE_FIELDS:
            row[f + "_int"], row[f + "_brk"] = m[f], one[f]
        pairs.append(row)
        used |= set(lines["broker_row"])
    if not pairs:
        return result
    return _add_pairs(result, pd.DataFrame(pairs), used, internal, broker)


def match_all(internal: pd.DataFrame, broker: pd.DataFrame) -> MatchResult:
    """All four steps. This is what the rest of the engine calls."""
    lines = fold_fills(internal, broker)
    result = match_by_id(internal, lines)
    result = match_fallback(result, internal, lines)
    return match_fallback_fills(result, internal, lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Match the blotter to the broker statement.")
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--broker", default="data/broker_statement.csv")
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker = load_broker(args.broker)

    by_id_only = match_by_id(internal, broker)                 # no folding, no fallback
    result = match_all(internal, broker)

    print(f"internal rows: {len(internal)}   broker lines: {len(broker)}")
    print()
    print(f"{'':<30}{'ID only':>10}{'all four steps':>16}")
    for (name, a), b in zip(by_id_only.counts().items(), result.counts().values()):
        print(f"  {name:<28}{a:>10}{b:>16}")
    print()
    print("trades the broker reported as several fills:")
    multi = result.matched[result.matched["fills"] > 1]
    print(multi[["trade_id", "match_method", "fills", "broker_rows", "symbol_int", "quantity_int", "price_int", "price_brk"]]
          .rename(columns=lambda c: c.replace("_int", "").replace("price_brk", "avg_fill_price")).to_string(index=False))
    print()
    print("still unmatched, ours (these are the real missing trades):")
    print(result.unmatched_internal[["trade_id", "symbol", "side", "quantity", "trade_date"]].to_string(index=False))


if __name__ == "__main__":
    main()
