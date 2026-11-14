"""Night 5: market calendars and settlement dates.

Hard-coded for 2026 and 2027, from the exchanges' own published schedules:

    US closed days       NYSE holiday calendar, nyse.com/markets/hours-calendars
    HK closed days       HKEX circulars CT/075/25 (2026) and CT/077/26 (2027)

The important idea: "the market is open" and "trades can settle" are two
different questions, and each market has days where the answers differ.

    US   Columbus Day and Veterans Day. The exchanges trade, but banks are
         closed, so nothing settles. The next day settles two days of trades.
    HK   The half-day sessions before Lunar New Year, Christmas and New Year.
         HKEX's 2026 circular calls each a "non-settlement day".

A date outside 2026 to 2027 raises an error. The holidays there are not in
this file, and a silently wrong settlement date is worse than a crash.
"""
from __future__ import annotations

from datetime import date, timedelta

import config

COVERAGE = (date(2026, 1, 1), date(2027, 12, 31))

# Weekdays on which the market does not trade at all.
MARKET_CLOSED = {
    "US": {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
        date(2026, 11, 26), date(2026, 12, 25),
        date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
        date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
        date(2027, 11, 25), date(2027, 12, 24),
    },
    "HK": {
        date(2026, 1, 1), date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
        date(2026, 4, 3), date(2026, 4, 6), date(2026, 4, 7), date(2026, 5, 1),
        date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 1), date(2026, 10, 1),
        date(2026, 10, 19), date(2026, 12, 25),
        date(2027, 1, 1), date(2027, 2, 8), date(2027, 2, 9), date(2027, 3, 26),
        date(2027, 3, 29), date(2027, 4, 5), date(2027, 5, 13), date(2027, 6, 9),
        date(2027, 7, 1), date(2027, 9, 16), date(2027, 10, 1), date(2027, 10, 8),
        date(2027, 12, 27),
    },
}

# Days the market trades but nothing settles.
OPEN_BUT_NO_SETTLEMENT = {
    "US": {
        date(2026, 10, 12), date(2026, 11, 11),  # Columbus Day, Veterans Day
        date(2027, 10, 11), date(2027, 11, 11),
    },
    "HK": {
        date(2026, 2, 16), date(2026, 12, 24), date(2026, 12, 31),
        # UNVERIFIED for 2027: the 2027 circular lists these half-days but does
        # not repeat the words "non-settlement day". Assumed unchanged from 2026.
        date(2027, 2, 5), date(2027, 12, 24), date(2027, 12, 31),
    },
}


def _check_covered(d: date) -> None:
    if not (COVERAGE[0] <= d <= COVERAGE[1]):
        raise ValueError(f"{d} is outside the calendar's coverage "
                         f"({COVERAGE[0]} to {COVERAGE[1]}); add that year's holidays first")


def is_trading_day(market: str, d: date) -> bool:
    _check_covered(d)
    return d.weekday() < 5 and d not in MARKET_CLOSED[market]


def is_settlement_day(market: str, d: date) -> bool:
    return is_trading_day(market, d) and d not in OPEN_BUT_NO_SETTLEMENT[market]


def trading_days(market: str, start: date, end: date) -> list[date]:
    """Every day the market trades from start to end, inclusive."""
    days, d = [], start
    while d <= end:
        if is_trading_day(market, d):
            days.append(d)
        d += timedelta(days=1)
    return days


def add_settlement_days(market: str, d: date, n: int) -> date:
    """Move n settlement days forward (n > 0) or back (n < 0) from d."""
    step = 1 if n > 0 else -1
    while n != 0:
        d += timedelta(days=step)
        if is_settlement_day(market, d):
            n -= step
    return d


def settle_cycle(market: str, trade_date: date) -> int:
    """T+how many, for this market, as of this trade date (from config)."""
    days = None
    for effective_from, n in config.SETTLE_CYCLES[market]:
        if effective_from <= trade_date:
            days = n  # later entries override earlier ones
    if days is None:
        raise ValueError(f"no settlement cycle for {market} on {trade_date}")
    return days


def expected_settle_date(market: str, trade_date: date) -> date:
    """The date a trade done on trade_date should settle."""
    if not is_trading_day(market, trade_date):
        raise ValueError(f"{trade_date} is not a trading day in {market}")
    return add_settlement_days(market, trade_date, settle_cycle(market, trade_date))
