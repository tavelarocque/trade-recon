"""Night 6: grade the engine against the answer key.

This is the only module besides inject.py that reads ground_truth.csv, and
it is never imported by the engine. The engine produces a break list from
the two books alone. This module then asks two questions about that list.

    recall     of the breaks we planted, what fraction did the engine find?
    precision  of the breaks the engine reported, what fraction are real?

A break counts as found only if the trade and the type both match, and its
cash difference agrees with the answer key to the cent.
"""
from __future__ import annotations

import pandas as pd


def score(breaks: pd.DataFrame, truth: pd.DataFrame) -> dict:
    found = {(r.trade_id, r.break_type): r.cash_diff for r in breaks.itertuples() if isinstance(r.trade_id, str)}
    # Broker rows the engine could not attribute to any trade of ours.
    orphans = int(sum(not isinstance(t, str) for t in breaks["trade_id"]))
    planted = {(r.trade_id, r.break_type): r.cash_diff for r in truth.itertuples()}

    hits = [k for k in planted if k in found and abs(found[k] - planted[k]) < 0.005]
    missed = sorted(set(planted) - set(hits))
    false_alarms = sorted(set(found) - set(planted))
    reported = len(breaks)

    return {
        "planted": len(planted),
        "reported": reported,
        "true_positives": len(hits),
        "recall": len(hits) / len(planted) if planted else 1.0,
        "precision": len(hits) / reported if reported else 1.0,
        "missed": missed,
        "false_alarms": false_alarms,
        "orphan_rows": orphans,
    }


def summary(s: dict) -> str:
    lines = [
        f"recall     {s['true_positives']}/{s['planted']} = {s['recall']:.1%}   (planted breaks the engine found)",
        f"precision  {s['true_positives']}/{s['reported']} = {s['precision']:.1%}   (reported breaks that are real)",
    ]
    if s["missed"]:
        lines.append(f"missed: {s['missed']}")
    if s["false_alarms"] or s["orphan_rows"]:
        lines.append(f"false alarms: {s['false_alarms']}  plus {s['orphan_rows']} unattributed broker rows")
    return "\n".join(lines)
