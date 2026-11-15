"""Night 4: turn match results into classified, sized breaks.

Input:  the four buckets from match.py
Output: one row per break, with
    cash_diff    signed, local currency: our cash minus the broker's cash
    impact_usd   unsigned, in USD: how much attention the break deserves

and a totals check that proves the breaks explain the whole gap between
the two books.

Run:  python3 classify.py
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd

import config
from common import signed_cash
from match import MatchResult, match_all
from normalize import COMPARE_FIELDS, load_broker, load_internal

# A matched pair that differs on one of these fields gets a named break type.
# A difference on any other field (symbol, currency, trade date, account,
# broker) is reported as STATIC_DATA. The generator never plants those, but
# the engine must not stay silent just because nobody expected them.
FIELD_TO_TYPE = {
    "price": "PRICE",
    "quantity": "QUANTITY",
    "side": "SIDE",
    "fees": "FEE",
    "settle_date": "SETTLE_DATE",
}
MONEY_FIELDS = {"price": 4, "fees": 2}  # decimals to compare at

BREAK_COLUMNS = [
    "break_type", "trade_id", "broker_row", "field", "internal_value", "broker_value",
    "symbol", "side", "quantity", "price", "currency", "broker", "trade_date",
    "cash_diff", "impact_basis", "impact_local", "impact_usd", "match_method",
]


def row_cash(row, suffix: str = "") -> float:
    return signed_cash(row["side" + suffix], row["quantity" + suffix],
                       row["price" + suffix], row["fees" + suffix])


def differing_fields(pair) -> list[str]:
    """Which compare-fields disagree between our side and the broker's.

    Money fields are compared after rounding, because two floats that print
    the same can differ in the 15th decimal. A difference no bigger than the
    field's tolerance in config.py is not a break.
    """
    out = []
    for f in COMPARE_FIELDS:
        ours, theirs = pair[f + "_int"], pair[f + "_brk"]
        if f in MONEY_FIELDS:
            gap = abs(round(ours - theirs, MONEY_FIELDS[f]))
            same = gap <= config.TOLERANCE.get(f, 0.0) + 1e-9
        else:
            same = ours == theirs
        if not same:
            out.append(f)
    return out


def within_tolerance(result: MatchResult) -> pd.DataFrame:
    """Matched pairs that agree within tolerance but not to the cent.

    These are not breaks. They are listed so the cents are never lost: the
    totals check adds them back, and the report shows how much was waved
    through. A tolerance that hides money without counting it is a bug.
    """
    rows = []
    for _, pair in result.matched.iterrows():
        if differing_fields(pair):
            continue
        cash_diff = round(row_cash(pair, "_int") - row_cash(pair, "_brk"), 2)
        if cash_diff != 0:
            rows.append({"trade_id": pair["trade_id"], "broker_row": pair["broker_row"],
                         "currency": pair["currency_int"], "our_fees": pair["fees_int"],
                         "broker_fees": pair["fees_brk"], "cash_diff": cash_diff})
    return pd.DataFrame(rows, columns=["trade_id", "broker_row", "currency", "our_fees", "broker_fees", "cash_diff"])


def size(cash_diff: float, notional: float, currency: str) -> dict:
    """How big is this break, for ranking?

    If cash is in dispute, the size is the disputed cash. If no cash is in
    dispute (a settlement date or account mismatch), the trade can still fail
    to settle, so the size is the whole notional, labelled as at risk.
    """
    if round(cash_diff, 2) != 0:
        basis, local = "cash difference", abs(cash_diff)
    else:
        basis, local = "notional at risk", abs(notional)
    return {
        "impact_basis": basis,
        "impact_local": round(local, 2),
        "impact_usd": round(local * config.USD_PER[currency], 2),
    }


def classify(result: MatchResult) -> pd.DataFrame:
    breaks: list[dict] = []

    # 1. Matched pairs: both sides have the trade. Do they agree on it?
    for _, pair in result.matched.iterrows():
        fields = differing_fields(pair)
        if not fields:
            continue  # a clean trade: the common case, and not a break
        if len(fields) == 1:
            f = fields[0]
            break_type = FIELD_TO_TYPE.get(f, "STATIC_DATA")
            field, ours, theirs = f, pair[f + "_int"], pair[f + "_brk"]
        else:
            # Several fields differ on one trade. Report it once, so its cash
            # is counted once, and list every field for the analyst.
            break_type = "MULTIPLE"
            field = "+".join(fields)
            ours = "; ".join(str(pair[f + "_int"]) for f in fields)
            theirs = "; ".join(str(pair[f + "_brk"]) for f in fields)

        cash_diff = round(row_cash(pair, "_int") - row_cash(pair, "_brk"), 2)
        notional = pair["quantity_int"] * pair["price_int"]
        breaks.append({
            "break_type": break_type, "trade_id": pair["trade_id"], "broker_row": pair["broker_row"],
            "field": field, "internal_value": ours, "broker_value": theirs,
            "symbol": pair["symbol_int"], "side": pair["side_int"], "quantity": pair["quantity_int"],
            "price": pair["price_int"], "currency": pair["currency_int"], "broker": pair["broker_int"],
            "trade_date": pair["trade_date_int"], "match_method": pair["match_method"],
            "cash_diff": cash_diff, **size(cash_diff, notional, pair["currency_int"]),
        })

    # 2. Duplicates: the broker expects this cash a second time. We do not.
    for _, row in result.duplicates.iterrows():
        cash_diff = round(-row_cash(row), 2)
        breaks.append({
            "break_type": "DUPLICATE", "trade_id": row["trade_id"], "broker_row": row["broker_row"],
            "field": "(whole trade)", "internal_value": "1 row", "broker_value": "2 rows",
            **{k: row[k] for k in ("symbol", "side", "quantity", "price", "currency", "broker", "trade_date")},
            "cash_diff": cash_diff, **size(cash_diff, row["quantity"] * row["price"], row["currency"]),
        })

    # 3. Ours with no partner: we expect this cash, the broker expects none.
    for _, row in result.unmatched_internal.iterrows():
        cash_diff = round(row_cash(row), 2)
        breaks.append({
            "break_type": "MISSING", "trade_id": row["trade_id"], "broker_row": pd.NA,
            "field": "(whole trade)", "internal_value": "present", "broker_value": "absent",
            **{k: row[k] for k in ("symbol", "side", "quantity", "price", "currency", "broker", "trade_date")},
            "cash_diff": cash_diff, **size(cash_diff, row["quantity"] * row["price"], row["currency"]),
        })

    # 4. Theirs with no partner: the broker expects this cash, we expect none.
    for _, row in result.unmatched_broker.iterrows():
        cash_diff = round(-row_cash(row), 2)
        breaks.append({
            "break_type": "UNRECOGNISED", "trade_id": row["trade_id"], "broker_row": row["broker_row"],
            "field": "(whole trade)", "internal_value": "absent", "broker_value": "present",
            **{k: row[k] for k in ("symbol", "side", "quantity", "price", "currency", "broker", "trade_date")},
            "cash_diff": cash_diff, **size(cash_diff, row["quantity"] * row["price"], row["currency"]),
        })

    df = pd.DataFrame(breaks, columns=BREAK_COLUMNS)
    df["match_method"] = df["match_method"].fillna("")
    # Biggest first. Ties are broken by trade_id so the order is reproducible.
    return df.sort_values(["impact_usd", "trade_id"], ascending=[False, True],
                          na_position="last").reset_index(drop=True)


def totals_check(internal: pd.DataFrame, broker: pd.DataFrame, breaks: pd.DataFrame,
                 tolerated: pd.DataFrame | None = None) -> pd.DataFrame:
    """Do the breaks explain the entire gap between the two books?

    Per currency:  (our total cash) - (broker's total cash)  must equal the
    sum of cash_diff over all breaks, plus the cents waved through as within
    tolerance, to the cent. The gap is computed from the two raw books, line
    by line, so it does not depend on the matching being right.
    """
    ours = internal.apply(row_cash, axis=1).groupby(internal["currency"]).sum()
    theirs = broker.apply(row_cash, axis=1).groupby(broker["currency"]).sum()
    explained = breaks.groupby("currency")["cash_diff"].sum().astype(float)

    out = pd.DataFrame({"internal_cash": ours, "broker_cash": theirs}).fillna(0.0)
    out["gap"] = out["internal_cash"] - out["broker_cash"]
    out["sum_of_breaks"] = explained.reindex(out.index).fillna(0.0)
    waved = (tolerated.groupby("currency")["cash_diff"].sum() if tolerated is not None and len(tolerated)
             else pd.Series(dtype=float))
    out["within_tolerance"] = waved.reindex(out.index).fillna(0.0)
    out = out.round(2)
    out["unexplained"] = (out["gap"] - out["sum_of_breaks"] - out["within_tolerance"]).round(2) + 0.0  # no "-0.0"
    out["ok"] = out["unexplained"] == 0
    return out


@dataclass
class Reconciliation:
    result: MatchResult
    breaks: pd.DataFrame
    tolerated: pd.DataFrame
    totals: pd.DataFrame


def reconcile(internal: pd.DataFrame, broker: pd.DataFrame) -> Reconciliation:
    """The whole engine in one call: match, classify, and check the totals."""
    result = match_all(internal, broker)
    breaks = classify(result)
    tolerated = within_tolerance(result)
    return Reconciliation(result, breaks, tolerated, totals_check(internal, broker, breaks, tolerated))


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify and size the breaks.")
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--broker", default="data/broker_statement.csv")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker = load_broker(args.broker)
    rec = reconcile(internal, broker)
    breaks = rec.breaks

    print(f"{len(breaks)} breaks. Top {args.top} by impact in USD:")
    cols = ["break_type", "trade_id", "symbol", "currency", "internal_value", "broker_value",
            "cash_diff", "impact_basis", "impact_usd"]
    print(breaks[cols].head(args.top).to_string(index=False))
    print()
    print("by break type:")
    print(breaks.groupby("break_type").agg(count=("impact_usd", "size"),
                                           impact_usd=("impact_usd", "sum")).round(2)
          .sort_values("impact_usd", ascending=False).to_string())
    print()
    print("totals check (local currency, never summed across):")
    print(rec.totals.to_string())
    print()
    print(f"{len(rec.tolerated)} matched trades differ by a cent or less in fees and are not reported as breaks")


if __name__ == "__main__":
    main()
