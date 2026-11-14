"""Small helpers shared by every stage of the project."""
from __future__ import annotations


def signed_cash(side: str, quantity: float, price: float, fees: float) -> float:
    """Cash this trade moves, from our firm's point of view, in local currency.

    Buying costs money, so a BUY is negative. Selling brings money in, so a
    SELL is positive. Fees always cost money, on either side.

        BUY  100 @ 10.00, fees 1.00  ->  -1001.00
        SELL 100 @ 10.00, fees 1.00  ->   +999.00
    """
    notional = quantity * price
    if side == "BUY":
        return round(-notional - fees, 2)
    if side == "SELL":
        return round(notional - fees, 2)
    raise ValueError(f"unknown side: {side!r}")
