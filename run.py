"""Run the whole pipeline once and grade it.

    python3 run.py                 seed from config.py
    python3 run.py --seed 7
    python3 run.py --seeds 1-20    many seeds, one line each

Steps: generate the blotter, build the broker statement, run the engine on
those two files only, then grade the result against the answer key.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import config
import generate
import inject
from classify import reconcile
from evaluate import score, summary
from normalize import load_broker, load_internal
from report import write_report


def run_seed(seed: int, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    generate.generate(seed).to_csv(outdir / "internal_blotter.csv", index=False)
    internal = load_internal(outdir / "internal_blotter.csv")
    broker_raw, truth, noise = inject.inject(internal, seed)
    broker_raw.to_csv(outdir / "broker_statement.csv", index=False)
    truth.to_csv(outdir / "ground_truth.csv", index=False)
    noise.to_csv(outdir / "noise_log.csv", index=False)

    # The engine: two files in, a break list out. No answer key.
    broker = load_broker(outdir / "broker_statement.csv")
    rec = reconcile(internal, broker)

    return rec, score(rec.breaks, truth), (internal, broker)


def parse_seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate, reconcile and grade.")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--seeds", default=None, help="for example 1-20 or 3,5,8")
    args = parser.parse_args()

    if args.seeds:
        print(f"{'seed':>5} {'planted':>8} {'reported':>9} {'recall':>8} {'precision':>10} {'totals':>7}")
        all_ok = True
        with tempfile.TemporaryDirectory() as tmp:
            for seed in parse_seeds(args.seeds):
                rec, s, _ = run_seed(seed, Path(tmp) / str(seed))
                ok = bool(rec.totals["ok"].all())
                all_ok &= ok and s["recall"] == 1 and s["precision"] == 1
                print(f"{seed:>5} {s['planted']:>8} {s['reported']:>9} {s['recall']:>8.1%} {s['precision']:>10.1%} {'ok' if ok else 'FAIL':>7}")
        print("every seed perfect" if all_ok else "at least one seed is not perfect")
        sys.exit(0 if all_ok else 1)  # a non-zero exit fails the CI job

    rec, s, (internal, broker) = run_seed(args.seed, Path("data"))
    result, breaks, totals = rec.result, rec.breaks, rec.totals
    write_report(internal, broker, internal["trade_date"].max())
    print(f"seed {args.seed}: {len(breaks)} breaks reported")
    print(breaks.groupby("break_type").agg(count=("impact_usd", "size"), impact_usd=("impact_usd", "sum"))
          .round(2).sort_values("impact_usd", ascending=False).to_string())
    print()
    c = result.counts()
    print(f"paired without a usable reference (fallback match): {c['of which by fallback']}")
    print(f"trades the broker reported as several fills, folded into one: {c['of which from several fills']}")
    print(f"fee differences within tolerance, not reported as breaks: {len(rec.tolerated)}")
    print()
    print("totals check:")
    print(totals.to_string())
    print()
    print("report written to reports/break_report.md and reports/break_report.csv")
    print()
    print(summary(s))
    if not (s["recall"] == 1 and s["precision"] == 1 and totals["ok"].all()):
        sys.exit(1)


if __name__ == "__main__":
    main()
