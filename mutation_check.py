"""Do the tests have teeth? Plant bugs in the engine and see if they notice.

A test suite that passes proves little on its own, because a suite that
checks nothing also passes. This script copies the project to a temporary
folder once per planted bug, breaks one thing in each copy, and runs the tests.
Every copy must fail. A copy that still passes is a bug the suite cannot see.

Nothing in the real project folder is changed.

Run:  python3 mutation_check.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (what is broken, file, original text, replacement)
BUGS = [
    ("fees compared to the dollar, not the cent", "classify.py",
     'MONEY_FIELDS = {"price": 4, "fees": 2}', 'MONEY_FIELDS = {"price": 4, "fees": 0}'),
    ("duplicate cash given the wrong sign", "classify.py",
     "    for _, row in result.duplicates.iterrows():\n        cash_diff = round(-row_cash(row), 2)",
     "    for _, row in result.duplicates.iterrows():\n        cash_diff = round(row_cash(row), 2)"),
    ("side flips ignored", "classify.py", '    "side": "SIDE",\n', ""),
    ("settlement breaks sized at zero", "classify.py",
     '        basis, local = "notional at risk", abs(notional)', '        basis, local = "notional at risk", 0.0'),
    ("whitespace not stripped", "normalize.py",
     "        df[col] = df[col].str.strip()", "        df[col] = df[col]"),
    ("symbols not upper-cased", "normalize.py",
     'for col in ("trade_id", "symbol", "side", "currency", "account", "broker"):',
     'for col in ("trade_id", "side", "currency", "account", "broker"):'),
    ("compact dates read day-first", "config.py", '"%Y%m%d"]', '"%Y%d%m"]'),
    ("fallback match switched off", "match.py",
     "    result = match_fallback(result, internal, lines)\n", ""),
    ("fills treated as duplicates, not folded", "match.py",
     "    lines = fold_fills(internal, broker)\n", "    lines = with_line_columns(broker)\n"),
    ("unreferenced fills paired without checking they add up", "match.py",
     'if len(mine) != 1 or int(lines["quantity"].sum()) != int(mine.iloc[0]["quantity"]):',
     "if len(mine) != 1:"),
    ("fee tolerance set to a dollar", "config.py",
     'TOLERANCE = {"price": 0.0, "fees": 0.01}', 'TOLERANCE = {"price": 0.0, "fees": 1.0}'),
    ("tolerated cents dropped from the totals check", "classify.py",
     '(out["gap"] - out["sum_of_breaks"] - out["within_tolerance"])', '(out["gap"] - out["sum_of_breaks"])'),
    ("fallback match guesses between two candidates", "match.py",
     "    ours_unique = ours[~ours.duplicated(FALLBACK_KEY, keep=False)]",
     "    ours_unique = ours.drop_duplicates(FALLBACK_KEY)"),
    ("fees added on a sell", "common.py",
     "        return round(notional - fees, 2)", "        return round(notional + fees, 2)"),
    ("Veterans Day treated as a settlement day", "calendars.py",
     "date(2026, 10, 12), date(2026, 11, 11),", "date(2026, 10, 12),"),
    ("Hong Kong half-day treated as a settlement day", "calendars.py",
     "date(2026, 2, 16), date(2026, 12, 24), date(2026, 12, 31),", "date(2026, 12, 24), date(2026, 12, 31),"),
]


def main() -> int:
    caught = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, filename, old, new) in enumerate(BUGS):
            copy = Path(tmp) / f"bug{i}"
            shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns(
                ".venv", "data", "__pycache__", ".pytest_cache", ".git"))
            target = copy / filename
            text = target.read_text()
            if text.count(old) != 1:
                print(f"SKIPPED  {name}: the code it targets has changed, update BUGS")
                continue
            target.write_text(text.replace(old, new))
            run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                                 cwd=copy, capture_output=True, text=True)
            if run.returncode != 0:
                caught += 1
                first_fail = next((l for l in run.stdout.splitlines() if l.startswith("FAILED")), "")
                test = first_fail.split("::")[-1].split(" ")[0].split("[")[0] if first_fail else "?"
                print(f"CAUGHT   {name:<48} by {test}")
            else:
                print(f"MISSED   {name}")
    print(f"\n{caught} of {len(BUGS)} planted bugs caught")
    return 0 if caught == len(BUGS) else 1


if __name__ == "__main__":
    sys.exit(main())
