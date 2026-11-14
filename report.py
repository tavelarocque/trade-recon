"""Night 7: the report an analyst would actually read.

Runs the engine on the two books and writes

    reports/break_report.csv   every break, biggest impact first
    reports/break_report.md    the same, readable, with summaries on top

Each break carries a one-line suggested action. The report never reads the
answer key; grading is run.py's job.

Run:  python3 report.py
      python3 report.py --as-of 2026-11-12
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from classify import classify, totals_check
from match import match_all
from normalize import load_broker, load_internal
from settlement import annotate, audit_internal

REPORT_COLUMNS = [
    "rank", "break_type", "trade_id", "broker_row", "broker", "symbol", "side", "quantity", "price",
    "currency", "trade_date", "expected_settle_date", "settle_status", "field", "internal_value",
    "broker_value", "cash_diff", "impact_basis", "impact_local", "impact_usd", "wrong_side",
    "match_method", "suggested_action",
]


def suggested_action(b) -> str:
    """One line telling the analyst what to do about this break."""
    t, broker = b["break_type"], b["broker"]
    if t == "PRICE":
        return f"Confirm the execution price with {broker}: we have {b['internal_value']}, they have {b['broker_value']}."
    if t == "QUANTITY":
        return f"Confirm the filled quantity with {broker}: we have {b['internal_value']}, they have {b['broker_value']}. Check for a partial fill."
    if t == "SIDE":
        return f"Confirm the direction with the trader and {broker} first: the books differ by twice the notional."
    if t == "FEE":
        return f"Check {broker}'s fee against the agreed schedule: we expect {b['internal_value']}, they charged {b['broker_value']}."
    if t == "SETTLE_DATE":
        exp = b["expected_settle_date"]
        if b["wrong_side"] == "broker":
            return f"Ask {broker} to amend the settlement date to {exp}; ours matches the calendar."
        if b["wrong_side"] == "us":
            return f"Correct our booking to settle {exp}; {broker}'s date matches the calendar."
        return f"Neither date matches the calendar ({exp}): correct our booking and ask {broker} to amend theirs."
    if t == "MISSING":
        return f"{broker} has no record of this trade: send them the details and confirm it was executed."
    if t == "DUPLICATE":
        return f"{broker} shows this trade twice (statement line {b['broker_row']}): ask them to cancel the repeat."
    if t == "UNRECOGNISED":
        return f"We have no record of {broker}'s statement line {b['broker_row']}: ask the trader whether a trade went unbooked."
    if t == "STATIC_DATA":
        return f"Reference data differs on {b['field']}: we have {b['internal_value']}, {broker} has {b['broker_value']}."
    return f"Several fields differ ({b['field']}): review the whole trade with {broker}."


def build_report(internal: pd.DataFrame, broker: pd.DataFrame, as_of: date) -> pd.DataFrame:
    breaks = annotate(classify(match_all(internal, broker)), as_of)
    breaks["suggested_action"] = [suggested_action(b) for _, b in breaks.iterrows()]
    breaks.insert(0, "rank", range(1, len(breaks) + 1))
    return breaks[REPORT_COLUMNS]


def by_type(report: pd.DataFrame) -> pd.DataFrame:
    return (report.groupby("break_type").agg(count=("rank", "size"), impact_usd=("impact_usd", "sum"))
            .round(2).sort_values("impact_usd", ascending=False).reset_index())


def by_broker(report: pd.DataFrame) -> pd.DataFrame:
    return (report.groupby("broker").agg(count=("rank", "size"), impact_usd=("impact_usd", "sum"))
            .round(2).sort_values("impact_usd", ascending=False).reset_index())


def by_type_and_currency(report: pd.DataFrame) -> pd.DataFrame:
    """Signed cash, in local currency. HKD and USD are never added together."""
    return (report.groupby(["break_type", "currency"]).agg(count=("rank", "size"), cash_diff=("cash_diff", "sum"))
            .round(2).reset_index())


def md_table(df: pd.DataFrame, money: tuple[str, ...] = ()) -> str:
    def cell(col, v):
        if col in money and pd.notna(v):
            return f"{v:,.2f}"
        return "" if pd.isna(v) else str(v)
    head = "| " + " | ".join(df.columns) + " |"
    rule = "| " + " | ".join("---:" if c in money or c in ("count", "rank", "quantity") else "---" for c in df.columns) + " |"
    rows = ["| " + " | ".join(cell(c, v) for c, v in zip(df.columns, r)) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, rule] + rows)


def to_markdown(report, totals, internal, broker, as_of, repaired, own_errors, top=15) -> str:
    money = ("impact_usd", "cash_diff", "internal_cash", "broker_cash", "gap", "sum_of_breaks", "unexplained")
    out = [
        "# Trade break report",
        "",
        f"Report date {as_of}. Our blotter has {len(internal)} trades and the broker statement has {len(broker)} lines.",
        "",
        f"**{len(report)} breaks, {report['impact_usd'].sum():,.2f} USD of total impact.** "
        f"The largest is a {report.iloc[0]['break_type']} on {report.iloc[0]['trade_id']} "
        f"worth {report.iloc[0]['impact_usd']:,.2f} USD." if len(report) else "**No breaks.**",
        "",
        "## Does it add up?",
        "",
        "Our total cash minus the broker's total cash, compared with the sum of the breaks, in each currency.",
        "",
        md_table(totals.reset_index(), money),
        "",
        "## By break type",
        "",
        md_table(by_type(report), money),
        "",
        "## By broker",
        "",
        md_table(by_broker(report), money),
        "",
        "## By urgency",
        "",
        md_table(report.groupby("settle_status").agg(count=("rank", "size"), impact_usd=("impact_usd", "sum"))
                 .round(2).reset_index(), money),
        "",
        f"## Top {min(top, len(report))} breaks",
        "",
        md_table(report.head(top)[["rank", "break_type", "trade_id", "broker", "symbol", "currency",
                                   "cash_diff", "impact_usd", "settle_status", "suggested_action"]], money),
        "",
        "## Notes",
        "",
        f"- {repaired} broker lines had no usable trade reference and were paired by symbol, side, quantity and trade date. They are not breaks.",
        f"- {own_errors} of our own trades have a settlement date that disagrees with the calendar.",
        "- Impact is the absolute cash difference in USD at a fixed rate. Where no cash is in dispute, it is the trade's notional, marked as notional at risk.",
        "- The full list is in `break_report.csv`.",
        "",
    ]
    return "\n".join(out)


def write_report(internal, broker, as_of, outdir: Path = Path("reports")):
    result = match_all(internal, broker)
    report = build_report(internal, broker, as_of)
    totals = totals_check(internal, broker, classify(result))
    repaired = int((result.matched["match_method"] == "fallback").sum())
    own_errors = len(audit_internal(internal))

    outdir.mkdir(parents=True, exist_ok=True)
    report.to_csv(outdir / "break_report.csv", index=False)
    (outdir / "break_report.md").write_text(
        to_markdown(report, totals, internal, broker, as_of, repaired, own_errors))
    return report, totals


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the ranked break report.")
    parser.add_argument("--internal", default="data/internal_blotter.csv")
    parser.add_argument("--broker", default="data/broker_statement.csv")
    parser.add_argument("--as-of", default=None, help="report date, YYYY-MM-DD (default: last trade date)")
    parser.add_argument("--outdir", default="reports")
    args = parser.parse_args()

    internal = load_internal(args.internal)
    broker = load_broker(args.broker)
    as_of = (datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of
             else internal["trade_date"].max())

    report, totals = write_report(internal, broker, as_of, Path(args.outdir))

    print(f"{len(report)} breaks, {report['impact_usd'].sum():,.2f} USD of impact, as of {as_of}")
    print()
    print(by_type(report).to_string(index=False))
    print()
    print(by_broker(report).to_string(index=False))
    print()
    print("top 5:")
    for _, b in report.head(5).iterrows():
        print(f"  {b['rank']:>2}. {b['break_type']:<12}{b['trade_id']:<9}{b['impact_usd']:>13,.2f} USD  {b['suggested_action']}")
    print()
    print("totals check ok:", bool(totals["ok"].all()))
    print(f"wrote {args.outdir}/break_report.csv and {args.outdir}/break_report.md")


if __name__ == "__main__":
    main()
