"""The verification suite. Run from the project folder with:  pytest -q

Every test builds its own data from a seed in a temporary folder, runs the
engine on the two books only, and grades the result against the answer key.
Nothing here reads or writes the data/ folder.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
import tempfile

import pandas as pd
import pytest

import config
import generate
import inject
from calendars import expected_settle_date, is_trading_day
from classify import classify, reconcile, totals_check
from common import signed_cash
from evaluate import score
from match import fold_fills, match_all, match_by_id
from normalize import load_broker, load_internal, parse_date
from settlement import annotate, audit_internal

SEEDS = list(range(1, 21)) + [42]
_TMP = Path(tempfile.mkdtemp(prefix="trade-recon-tests-"))


@lru_cache(maxsize=None)
def pipeline(seed: int, scale: int = 1, breaks: bool = True, noise: bool = True):
    """Generate, inject, load. Returns (internal, broker, truth, noise_log)."""
    d = _TMP / f"s{seed}-x{scale}-b{int(breaks)}-n{int(noise)}"
    d.mkdir(parents=True, exist_ok=True)
    generate.generate(seed).to_csv(d / "internal.csv", index=False)
    internal = load_internal(d / "internal.csv")
    raw, truth, noise_log = inject.inject(
        internal, seed,
        break_counts={k: (v * scale if breaks else 0) for k, v in config.BREAK_COUNTS.items()},
        noise_counts={k: (v * scale if noise else 0) for k, v in config.NOISE_COUNTS.items()},
        date_format_noise=None if noise else 0.0,
    )
    raw.to_csv(d / "broker.csv", index=False)
    return internal, load_broker(d / "broker.csv"), truth, noise_log


def engine(internal, broker):
    return reconcile(internal, broker).breaks


def ids(noise_log, *types):
    return set(noise_log.loc[noise_log["noise_type"].isin(types), "trade_id"])


# ---------------------------------------------------------------- the headline

@pytest.mark.parametrize("seed", SEEDS)
def test_every_planted_break_is_found_and_nothing_else(seed):
    internal, broker, truth, _ = pipeline(seed)
    s = score(engine(internal, broker), truth)
    assert s["missed"] == []
    assert s["false_alarms"] == [] and s["orphan_rows"] == 0
    assert s["recall"] == 1.0 and s["precision"] == 1.0


@pytest.mark.parametrize("seed", SEEDS)
def test_totals_reconcile_to_the_cent(seed):
    internal, broker, _, _ = pipeline(seed)
    totals = reconcile(internal, broker).totals
    assert totals["ok"].all(), totals.to_string()


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_three_times_as_many_breaks_and_noise(seed):
    internal, broker, truth, _ = pipeline(seed, scale=3)
    assert len(truth) == 3 * sum(config.BREAK_COUNTS.values())
    rec = reconcile(internal, broker)
    s = score(rec.breaks, truth)
    assert s["recall"] == 1.0 and s["precision"] == 1.0
    assert rec.totals["ok"].all()


# ------------------------------------------------------------ false positives

@pytest.mark.parametrize("seed", [1, 2, 3, 42])
def test_noise_alone_produces_zero_breaks(seed):
    """A statement with every kind of formatting mess and no real break."""
    internal, broker, truth, noise_log = pipeline(seed, breaks=False)
    assert truth.empty and not noise_log.empty
    assert engine(internal, broker).empty


def test_identical_books_produce_zero_breaks():
    internal, broker, _, _ = pipeline(7, breaks=False, noise=False)
    assert engine(internal, broker).empty


@pytest.mark.parametrize("seed", SEEDS)
def test_blank_references_are_repaired_not_reported(seed):
    internal, broker, _, noise_log = pipeline(seed)
    result = match_all(internal, broker)
    repaired = set(result.matched.loc[result.matched["match_method"] == "fallback", "trade_id"])
    assert repaired == ids(noise_log, "MISSING_ID", "SPLIT_NO_REF")
    assert result.unmatched_broker.empty


def test_without_the_fallback_precision_drops():
    """Documents why the fallback exists: without it, every trade the broker
    sent with no reference shows up twice, as missing and as unrecognised."""
    internal, broker, truth, noise_log = pipeline(42)
    result = match_by_id(internal, fold_fills(internal, broker))
    s = score(classify(result), truth)
    no_ref = ids(noise_log, "MISSING_ID", "SPLIT_NO_REF")
    assert s["recall"] == 1.0
    assert s["reported"] == len(truth) + len(no_ref) + len(result.unmatched_broker)
    assert s["precision"] < 0.6


def test_fallback_refuses_to_guess_between_two_candidates():
    internal, broker, _, noise_log = pipeline(42)
    blank_id = noise_log.loc[noise_log["noise_type"] == "MISSING_ID", "trade_id"].iloc[0]
    twin = internal[internal["trade_id"] == blank_id].copy()
    twin["trade_id"] = "T999999"  # a second trade of ours with the same fallback key
    internal2 = pd.concat([internal, twin], ignore_index=True)
    result = match_all(internal2, broker)
    assert blank_id in set(result.unmatched_internal["trade_id"])
    assert "T999999" in set(result.unmatched_internal["trade_id"])
    assert len(result.unmatched_broker) == 1


# ------------------------------------------------------ fills and tolerances

@pytest.mark.parametrize("seed", SEEDS)
def test_fills_are_folded_into_one_trade_and_not_reported(seed):
    internal, broker, truth, noise_log = pipeline(seed)
    rec = reconcile(internal, broker)
    folded = set(rec.result.matched.loc[rec.result.matched["fills"] > 1, "trade_id"])
    assert folded == ids(noise_log, "SPLIT_FILL", "SPLIT_NO_REF")
    assert not (set(rec.breaks["trade_id"].dropna()) & folded)
    # The average price over the fills equals our price on every folded trade.
    m = rec.result.matched[rec.result.matched["fills"] > 1]
    assert ((m["price_int"] - m["price_brk"]).abs() < 1e-6).all()


@pytest.mark.parametrize("seed", SEEDS)
def test_one_cent_fee_differences_are_tolerated_and_still_counted(seed):
    internal, broker, _, noise_log = pipeline(seed)
    rec = reconcile(internal, broker)
    assert set(rec.tolerated["trade_id"]) == ids(noise_log, "FEE_ROUNDING")
    assert (rec.tolerated["cash_diff"].abs().round(2) == 0.01).all()
    # Leave the tolerated cents out and the books no longer add up.
    assert not totals_check(internal, broker, rec.breaks)["ok"].all()


def test_zero_tolerance_turns_rounding_into_false_breaks(monkeypatch):
    internal, broker, truth, noise_log = pipeline(42)
    monkeypatch.setitem(config.TOLERANCE, "fees", 0.0)
    rec = reconcile(internal, broker)
    s = score(rec.breaks, truth)
    assert s["recall"] == 1.0
    assert s["reported"] == len(truth) + len(ids(noise_log, "FEE_ROUNDING"))
    assert rec.totals["ok"].all() and rec.tolerated.empty


def test_a_loose_tolerance_hides_real_breaks_but_never_hides_the_money(monkeypatch):
    internal, broker, truth, _ = pipeline(42)
    monkeypatch.setitem(config.TOLERANCE, "fees", 1000.0)
    rec = reconcile(internal, broker)
    s = score(rec.breaks, truth)
    assert s["recall"] < 1.0 and all(k[1] == "FEE" for k in s["missed"])
    assert rec.totals["ok"].all()          # the hidden fee breaks are still in the totals
    assert len(rec.tolerated) > 20


def _one_split(noise_log, broker, kind):
    tid = sorted(ids(noise_log, kind))[0]
    return tid


def test_a_missing_fill_is_a_quantity_break():
    internal, broker, _, noise_log = pipeline(42)
    tid = _one_split(noise_log, broker, "SPLIT_FILL")
    lines = broker[broker["trade_id"] == tid]
    short = broker.drop(index=lines.index[-1])          # the broker never sent the last fill
    rec = reconcile(internal, short)
    row = rec.breaks[rec.breaks["trade_id"] == tid]
    assert list(row["break_type"]) in (["QUANTITY"], ["MULTIPLE"])
    assert "quantity" in row["field"].item()
    assert rec.totals["ok"].all()


def test_equal_fills_at_one_price_are_fills_not_duplicates():
    """Two identical lines are duplicates only if they do NOT add up to ours."""
    internal, broker, _, noise_log = pipeline(42)
    tid = sorted(t for t in ids(noise_log, "SPLIT_FILL")
                 if len(broker[broker["trade_id"] == t]) == 2)[0]
    internal, b = internal.copy(), broker.copy()
    idx = b.index[b["trade_id"] == tid]
    i = internal.index[internal["trade_id"] == tid][0]
    half_fee = round(internal.loc[i, "fees"] / 2, 2)
    internal.loc[i, "fees"] = round(2 * half_fee, 2)     # make our fee split into two equal cents
    b.loc[idx, "price"] = internal.loc[i, "price"]       # both fills at our price
    b.loc[idx, "fees"] = half_fee                        # the two lines are now exact copies
    rec = reconcile(internal, b)
    assert tid not in set(rec.breaks["trade_id"].dropna())
    assert rec.result.duplicates[rec.result.duplicates["trade_id"] == tid].empty


def test_fills_that_disagree_on_settlement_are_not_folded_silently():
    internal, broker, _, noise_log = pipeline(42)
    tid = _one_split(noise_log, broker, "SPLIT_FILL")
    b = broker.copy()
    i = b.index[b["trade_id"] == tid][0]
    b.loc[i, "settle_date"] = date(2026, 12, 1)
    rec = reconcile(internal, b)
    assert tid in set(rec.breaks["trade_id"].dropna())   # it must surface, in some form


def test_unreferenced_fills_are_not_paired_when_they_do_not_add_up():
    internal, broker, _, noise_log = pipeline(42)
    tid = _one_split(noise_log, broker, "SPLIT_NO_REF")
    ours = internal[internal["trade_id"] == tid].iloc[0]
    b = broker.copy()
    cell = (b["trade_id"].isna() & (b["symbol"] == ours["symbol"]) & (b["side"] == ours["side"])
            & (b["trade_date"] == ours["trade_date"]))
    assert cell.sum() >= 2
    b.loc[b.index[cell][0], "quantity"] += 100
    result = match_all(internal, b)
    assert tid in set(result.unmatched_internal["trade_id"])
    assert len(result.unmatched_broker) == cell.sum()


def test_unreferenced_fills_are_not_paired_when_two_of_ours_could_fit():
    internal, broker, _, noise_log = pipeline(42)
    tid = _one_split(noise_log, broker, "SPLIT_NO_REF")
    twin = internal[internal["trade_id"] == tid].copy()
    twin["trade_id"] = "T999998"
    internal2 = pd.concat([internal, twin], ignore_index=True)
    result = match_all(internal2, broker)
    assert {tid, "T999998"} <= set(result.unmatched_internal["trade_id"])


# ------------------------------------------------------------------ bookkeeping

@pytest.mark.parametrize("seed", SEEDS)
def test_no_row_is_lost_or_counted_twice(seed):
    internal, broker, _, _ = pipeline(seed)
    r = match_all(internal, broker)
    assert len(r.matched) + len(r.unmatched_internal) == len(internal)
    # Every broker line is counted once: a matched trade may hold several fills.
    assert r.matched["fills"].sum() + len(r.duplicates) + len(r.unmatched_broker) == len(broker)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_same_seed_gives_identical_data(seed):
    a, b = generate.generate(seed), generate.generate(seed)
    assert a.equals(b)
    internal, _, _, _ = pipeline(seed)
    x, y = inject.inject(internal, seed), inject.inject(internal, seed)
    assert all(p.equals(q) for p, q in zip(x, y))


def test_generated_blotter_obeys_its_own_rules():
    internal, _, _, _ = pipeline(42)
    assert internal["trade_id"].is_unique
    assert not internal.duplicated(["symbol", "side", "quantity", "trade_date"]).any()
    for row in internal.itertuples():
        lot = config.MARKETS[row.market]["symbols"][row.symbol][2]
        assert row.quantity % lot == 0
        assert is_trading_day(row.market, row.trade_date)


def test_hiding_one_break_fails_the_totals_check():
    internal, broker, _, _ = pipeline(42)
    rec = reconcile(internal, broker)
    cash_breaks = rec.breaks[rec.breaks["cash_diff"] != 0]
    hidden = rec.breaks.drop(cash_breaks.index[0])
    assert not totals_check(internal, broker, hidden, rec.tolerated)["ok"].all()


def test_ranking_is_biggest_first_and_settlement_breaks_are_sized_by_notional():
    internal, broker, _, _ = pipeline(42)
    breaks = engine(internal, broker)
    assert breaks["impact_usd"].is_monotonic_decreasing
    sd = breaks[breaks["break_type"] == "SETTLE_DATE"]
    assert (sd["cash_diff"] == 0).all() and (sd["impact_basis"] == "notional at risk").all()
    assert (sd["impact_usd"] > 0).all()


# -------------------------------------------------------------- unplanted cases

def test_two_wrong_fields_report_once_and_static_data_is_not_ignored():
    internal, broker, truth, noise_log = pipeline(42)
    broker = broker.copy()
    special = ids(noise_log, "SPLIT_FILL", "SPLIT_NO_REF", "FEE_ROUNDING")
    clean = broker[broker["trade_id"].notna() & ~broker["trade_id"].isin(truth["trade_id"])
                   & ~broker["trade_id"].isin(special)]
    a, c = clean.index[0], clean.index[1]
    broker.loc[a, "price"] += 1.0
    broker.loc[a, "fees"] += 5.0
    broker.loc[c, "account"] = "ACC-999"
    rec = reconcile(internal, broker)
    breaks = rec.breaks
    row_a = breaks[breaks["trade_id"] == broker.loc[a, "trade_id"]]
    row_c = breaks[breaks["trade_id"] == broker.loc[c, "trade_id"]]
    assert list(row_a["break_type"]) == ["MULTIPLE"]
    assert list(row_c["break_type"]) == ["STATIC_DATA"]
    assert rec.totals["ok"].all()


# ------------------------------------------------------------------ settlement

@pytest.mark.parametrize("market, trade, settle", [
    ("US", date(2026, 11, 10), date(2026, 11, 12)),  # Veterans Day trades but does not settle
    ("US", date(2026, 11, 11), date(2026, 11, 12)),  # double settlement day
    ("US", date(2026, 10, 9), date(2026, 10, 13)),   # Columbus Day
    ("US", date(2026, 11, 25), date(2026, 11, 27)),  # Thanksgiving; the early close still settles
    ("US", date(2026, 12, 24), date(2026, 12, 28)),  # Christmas then a weekend
    ("US", date(2026, 4, 2), date(2026, 4, 6)),      # Good Friday
    ("US", date(2027, 6, 17), date(2027, 6, 21)),    # Juneteenth observed
    ("US", date(2026, 11, 13), date(2026, 11, 16)),  # plain weekend
    ("HK", date(2026, 2, 13), date(2026, 2, 23)),    # Lunar New Year, half-day does not settle
    ("HK", date(2026, 4, 2), date(2026, 4, 9)),      # Easter and Ching Ming
    ("HK", date(2026, 12, 23), date(2026, 12, 29)),  # Christmas Eve half-day
    ("HK", date(2026, 9, 30), date(2026, 10, 5)),    # National Day
    ("HK", date(2026, 11, 12), date(2026, 11, 16)),  # plain weekend
])
def test_settlement_dates_against_the_published_calendars(market, trade, settle):
    assert expected_settle_date(market, trade) == settle


def test_calendar_refuses_what_it_does_not_know():
    with pytest.raises(ValueError):
        expected_settle_date("US", date(2026, 11, 26))   # Thanksgiving is not a trading day
    with pytest.raises(ValueError):
        expected_settle_date("HK", date(2028, 1, 3))     # outside the hard-coded years
    with pytest.raises(ValueError):
        expected_settle_date("HK", date(2027, 12, 30))   # would settle in 2028


@pytest.mark.parametrize("seed", [1, 2, 3, 42])
def test_our_own_settle_dates_are_right_and_the_broker_is_blamed(seed):
    internal, broker, _, _ = pipeline(seed)
    assert audit_internal(internal).empty
    breaks = annotate(engine(internal, broker), internal["trade_date"].max())
    sd = breaks[breaks["break_type"] == "SETTLE_DATE"]
    assert len(sd) == config.BREAK_COUNTS["SETTLE_DATE"] and (sd["wrong_side"] == "broker").all()


def test_a_veterans_day_mistake_in_our_own_book_is_caught():
    internal, broker, truth, _ = pipeline(42)
    internal = internal.copy()
    candidates = internal[(internal["market"] == "US") & (internal["trade_date"] == date(2026, 11, 10))
                          & ~internal["trade_id"].isin(truth["trade_id"])]
    i = candidates.index[0]
    internal.loc[i, "settle_date"] = date(2026, 11, 11)
    assert list(audit_internal(internal)["trade_id"]) == [internal.loc[i, "trade_id"]]
    breaks = annotate(engine(internal, broker), date(2026, 11, 20))
    assert breaks.loc[breaks["trade_id"] == internal.loc[i, "trade_id"], "wrong_side"].item() == "us"


# ------------------------------------------------------------------- small parts

def test_signed_cash_convention():
    assert signed_cash("BUY", 100, 10.0, 1.0) == -1001.00
    assert signed_cash("SELL", 100, 10.0, 1.0) == 999.00
    with pytest.raises(ValueError):
        signed_cash("HOLD", 100, 10.0, 1.0)


def test_date_parser_reads_three_formats_and_refuses_the_rest():
    for text in ("2026-11-17", "17-Nov-2026", "20261117"):
        assert parse_date(text) == date(2026, 11, 17)
    for bad in ("03/04/2026", "", "2026-13-01"):
        with pytest.raises(ValueError):
            parse_date(bad)


def test_loader_stops_on_an_unknown_side_code(tmp_path):
    internal, _, _, _ = pipeline(42)
    raw, _, _ = inject.inject(internal, 42)
    raw.loc[0, "bs"] = "X"
    raw.to_csv(tmp_path / "b.csv", index=False)
    with pytest.raises(ValueError, match="unknown side codes"):
        load_broker(tmp_path / "b.csv")


# ----------------------------------------------------------------------- report

def test_report_is_complete_ranked_and_actionable(tmp_path):
    from report import by_broker, by_type, write_report
    internal, broker, truth, _ = pipeline(42)
    report, totals = write_report(internal, broker, internal["trade_date"].max(), tmp_path)

    assert (tmp_path / "break_report.csv").exists() and (tmp_path / "break_report.md").exists()
    assert len(report) == len(truth) and totals["ok"].all()
    assert list(report["rank"]) == list(range(1, len(report) + 1))
    assert report["impact_usd"].is_monotonic_decreasing
    assert report["suggested_action"].str.len().gt(20).all()
    # Every break names its broker, so the action says who to call.
    assert all(b in a for b, a in zip(report["broker"], report["suggested_action"]))
    # The two summaries are two cuts of the same list.
    total = round(report["impact_usd"].sum(), 2)
    assert round(by_type(report)["impact_usd"].sum(), 2) == total
    assert round(by_broker(report)["impact_usd"].sum(), 2) == total
    assert by_type(report)["count"].sum() == by_broker(report)["count"].sum() == len(report)
    text = (tmp_path / "break_report.md").read_text()
    assert "—" not in text


def test_report_csv_round_trips(tmp_path):
    from report import write_report
    internal, broker, _, _ = pipeline(7)
    report, _ = write_report(internal, broker, internal["trade_date"].max(), tmp_path)
    back = pd.read_csv(tmp_path / "break_report.csv")
    assert len(back) == len(report)
    assert (back["cash_diff"].round(2) == report["cash_diff"].round(2)).all()
