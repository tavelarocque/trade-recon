"""Every knob for the project lives here, so nothing is hard-coded elsewhere.

Reference prices, lot sizes and fee rates are illustrative, not live market data.
They only need to be realistic enough that the breaks look like real breaks.
"""
from datetime import date, time

# Reproducibility: the same seed always produces the same blotter.
SEED = 42
N_TRADES = 500
US_SHARE = 0.6  # fraction of trades that are US equities; the rest are Hong Kong

# Trade dates are drawn from each market's trading days in this window
# (inclusive). The window contains one trap on purpose: Wednesday
# 11 November 2026 is Veterans Day. US markets trade, but nothing settles.
TRADE_WINDOW = (date(2026, 11, 2), date(2026, 11, 20))

# Ranking needs one currency. Local currency stays on every row, and this
# fixed rate converts HKD to USD for ranking only. HKD is pegged near 7.8.
USD_PER = {"USD": 1.0, "HKD": 0.128}

# Settlement cycle per market as (effective_from, business_days) pairs.
# The US moved to T+1 on 2024-05-28. Hong Kong is T+2 today and HKEX has
# announced a move to T+1; when the date is final, add one line here.
SETTLE_CYCLES = {
    "US": [(date(2024, 5, 28), 1)],
    "HK": [(date(1990, 1, 1), 2)],
}

MARKETS = {
    "US": {
        "currency": "USD",
        "timezone": "America/New_York",
        "venues": ["NASDAQ", "NYSE", "ARCA"],
        "sessions": [(time(9, 30), time(16, 0))],
        "fee_bps": 0.5,     # fees as basis points of notional (1 bp = 0.01%)
        "max_lots": 2000,   # US lot size is 1, so this is max shares
        # symbol: (reference price, tick size, lot size)
        "symbols": {
            "AAPL": (228.00, 0.01, 1),
            "MSFT": (431.00, 0.01, 1),
            "NVDA": (139.00, 0.01, 1),
            "JPM": (243.00, 0.01, 1),
            "XOM": (118.00, 0.01, 1),
            "KO": (63.00, 0.01, 1),
        },
    },
    "HK": {
        "currency": "HKD",
        "timezone": "Asia/Hong_Kong",
        "venues": ["HKEX"],
        "sessions": [(time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))],
        "fee_bps": 13.0,    # stamp duty makes Hong Kong much more expensive
        "max_lots": 50,     # Hong Kong trades in board lots, not single shares
        "symbols": {
            "0700.HK": (410.00, 0.20, 100),
            "0005.HK": (72.00, 0.05, 400),
            "1299.HK": (60.00, 0.05, 200),
            "9988.HK": (95.00, 0.05, 100),
            "3690.HK": (180.00, 0.10, 100),
            "0939.HK": (6.20, 0.01, 1000),
        },
    },
}

PRICE_VOL = 0.02  # each trade price is the reference price moved by about 2%

# Fictional brokers and accounts.
BROKERS = ["NGS", "HLB", "PCM"]
ACCOUNTS = ["ACC-001", "ACC-002", "ACC-003", "ACC-004"]

# ---------------------------------------------------------------------------
# Night 2: what goes wrong on the broker's side
# ---------------------------------------------------------------------------

# Economic breaks: real disagreements. Each chosen trade gets exactly one.
BREAK_COUNTS = {
    "PRICE": 8,        # broker has a different price
    "QUANTITY": 6,     # broker has a different quantity
    "SIDE": 3,         # broker has BUY where we have SELL, or the reverse
    "FEE": 8,          # broker charged a different fee
    "SETTLE_DATE": 6,  # broker expects settlement on a different day
    "MISSING": 5,      # we have the trade, the broker does not
    "DUPLICATE": 4,    # broker shows the trade twice
}

# Noise: formatting mess that is NOT a disagreement. A careful analyst cleans
# it up first. The engine must never report any of this as a break.
NOISE_COUNTS = {
    "SYMBOL_CASE": 25,  # "aapl" instead of "AAPL"
    "WHITESPACE": 25,   # " AAPL  " instead of "AAPL"
    "MISSING_ID": 10,   # broker left our trade reference blank
}
DATE_FORMAT_NOISE = 0.3  # fraction of broker rows whose dates are not ISO

# The three date formats a broker row can use. All are unambiguous on purpose:
# a format like 03/04/2026 could mean 3 April or 4 March and cannot be fixed
# by code, only by asking the broker.
BROKER_DATE_FORMATS = ["%Y-%m-%d", "%d-%b-%Y", "%Y%m%d"]
