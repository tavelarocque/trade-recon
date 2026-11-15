# trade-recon

[![ci](https://github.com/tavelarocque/trade-recon/actions/workflows/ci.yml/badge.svg)](https://github.com/tavelarocque/trade-recon/actions/workflows/ci.yml)

A trade-break reconciliation engine. It compares a firm's internal trade blotter with a broker's statement, finds every disagreement, names it, sizes it in cash, and ranks the breaks by dollar impact with a suggested action for each.

Built in Python with pandas as a study of the daily work of a trading desk operations team: booking, reconciling against brokers, chasing breaks, and making sure trades settle.

## Results

Measured on synthetic data with breaks planted from a logged answer key that the engine never reads.

| Check | Result |
| --- | --- |
| Planted breaks found, 21 random seeds | 840 of 840 (100% recall) |
| False alarms | 0 (100% precision) |
| Statement with formatting noise only, no real breaks | 0 breaks reported |
| Trades the broker reported as 2 or 3 fills, with or without a reference | all folded into one trade, none reported as a break |
| One-cent fee rounding differences | none reported as a break, every cent still counted in the totals |
| Cash gap between the two books explained by the breaks | to the cent, in USD and HKD, on every seed |
| Same reconciliation rebuilt in Excel formulas only | agrees with pandas on every trade |
| Automated tests | 176 passing |
| Bugs deliberately planted in the engine | 16 of 16 caught by the tests |

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 run.py                 # generate, reconcile, write the report, grade
python3 run.py --seeds 1-20    # one line of recall and precision per seed
pytest -q                      # the test suite
python3 mutation_check.py      # plant 16 bugs, confirm each is caught
python3 excel_twin.py          # build the Excel workbooks
```

The report lands in `reports/break_report.md` and `reports/break_report.csv`.

## How it works

1. **Generate.** `generate.py` writes a seeded blotter of 500 US and Hong Kong equity trades. `inject.py` writes the broker's version: different column names, B and S for the side, three date formats, padded and lower-case symbols, blank trade references, fees rounded a cent differently, some trades reported as two or three fills, and 40 real breaks of seven types. Every planted break is logged with its cash effect.
2. **Normalize.** `normalize.py` reads the broker file as text, cleans it, and only then converts types. An unknown side code or an ambiguous date stops the run.
3. **Match.** `match.py` works in four steps. It folds broker lines that share a reference into one trade when they are fills (summed quantity, average price weighted by quantity, summed fees), and tells fills apart from duplicates by whether the quantities add up. It pairs by ID. It pairs leftovers one to one on symbol, side, quantity and trade date. Last, it pairs one trade of ours with several unreferenced fills when they add up to its quantity. Every fallback refuses to guess: if two candidates fit, it pairs neither.
4. **Classify and size.** `classify.py` names each break and gives it two numbers: a signed cash difference in local currency, and an absolute impact in USD for ranking. A settlement date break disputes no cash, so it is sized at the trade's notional and labelled as at risk. Fee differences inside a configurable tolerance are not breaks, but they are logged and their cents are carried into the totals check.
5. **Settlement.** `calendars.py` holds NYSE and HKEX calendars for 2026 and 2027, including the days that trade but do not settle (Columbus Day and Veterans Day in the US, half-day sessions in Hong Kong). `settlement.py` audits our own settle dates and says which side of a date break is wrong.
6. **Report.** `report.py` ranks the breaks, adds a one-line action, and summarises by type, broker and urgency.

## Verification

Three independent checks, because any one of them can pass while the engine is wrong.

- **Against the answer key.** `evaluate.py` scores recall and precision. A break counts only if the trade, the type and the cash to the cent all match.
- **Totals.** Our total cash minus the broker's total cash must equal the sum of the breaks plus the cents accepted as within tolerance, per currency. This is computed from the raw books and does not depend on the matching. It proves no cash is unaccounted for. It does not prove each break is right, because errors that cancel pass through it.
- **Against the outside world.** Settlement dates are tested against the exchanges' published calendars, and the cash convention against numbers worked out by hand. `mutation_check.py` shows why this matters: several of its sixteen planted bugs pass the answer-key test, because the generator and the engine share the wrong assumption, and only these outside checks catch them.

## Limits

- The data is synthetic and written by the same hand as the engine. Real broker files are messier in ways not planted here.
- Each trade carries at most one planted break. Blank references, fills and fee rounding appear only on otherwise clean trades.
- Fills are matched only when they add up to our quantity exactly. There is no search over subsets of lines and no many-to-many matching, and an unreferenced set of fills is paired only when no other trade of ours shares its symbol, side and date.
- Only fees have a tolerance. Prices are compared exactly.
- Calendars cover 2026 and 2027 only. Other dates raise an error.
- One FX rate, fixed in `config.py`, is used for ranking.
- Whether Hong Kong's 2027 half-days are non-settlement days is assumed from the 2026 schedule and marked unverified in the code.

## Files

| File | Purpose |
| --- | --- |
| `config.py` | Seed, counts, markets, fee rates, FX rate, settlement cycles |
| `generate.py`, `inject.py` | Test data and the answer key |
| `normalize.py`, `match.py`, `classify.py`, `settlement.py`, `report.py` | The engine |
| `calendars.py`, `common.py` | Shared: calendars and the cash sign convention |
| `evaluate.py`, `run.py` | Grading and the one-command pipeline |
| `tests/`, `mutation_check.py` | The test suite and the check on the tests |
| `excel_twin.py`, `excel/` | The Excel rebuild and practice workbooks |
| `NOTES.md` | The reasoning behind each stage, written as lessons |

## License

MIT, see [LICENSE](LICENSE). Written by Tave La Rocque, UBC Integrated Engineering.
