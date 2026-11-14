# Trade break report

Report date 2026-11-20. Our blotter has 500 trades and the broker statement has 499 lines.

**40 breaks, 3,395,486.72 USD of total impact.** The largest is a DUPLICATE on T000018 worth 805,032.20 USD.

## Does it add up?

Our total cash minus the broker's total cash, compared with the sum of the breaks, in each currency.

| currency | internal_cash | broker_cash | gap | sum_of_breaks | unexplained | ok |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| HKD | -6,313,678.31 | -5,909,449.06 | -404,229.25 | -404,229.25 | 0.00 | True |
| USD | -1,716,424.86 | -1,422,566.12 | -293,858.74 | -293,858.74 | 0.00 | True |

## By break type

| break_type | count | impact_usd |
| --- | ---: | ---: |
| MISSING | 5 | 1,079,101.64 |
| DUPLICATE | 4 | 924,106.86 |
| SIDE | 3 | 916,249.68 |
| SETTLE_DATE | 6 | 288,262.65 |
| QUANTITY | 6 | 184,790.12 |
| PRICE | 8 | 2,930.83 |
| FEE | 8 | 44.94 |

## By broker

| broker | count | impact_usd |
| --- | ---: | ---: |
| PCM | 15 | 1,531,944.18 |
| NGS | 12 | 965,561.09 |
| HLB | 13 | 897,981.45 |

## By urgency

| settle_status | count | impact_usd |
| --- | ---: | ---: |
| DUE_NEXT_DAY | 7 | 712,522.40 |
| DUE_TODAY | 4 | 767,328.53 |
| PAST_SETTLEMENT | 29 | 1,915,635.79 |

## Top 15 breaks

| rank | break_type | trade_id | broker | symbol | currency | cash_diff | impact_usd | settle_status | suggested_action |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | DUPLICATE | T000018 | PCM | MSFT | USD | 805,032.20 | 805,032.20 | PAST_SETTLEMENT | PCM shows this trade twice (statement line 308): ask them to cancel the repeat. |
| 2 | MISSING | T000455 | NGS | MSFT | USD | -668,866.76 | 668,866.76 | DUE_TODAY | NGS has no record of this trade: send them the details and confirm it was executed. |
| 3 | SIDE | T000113 | HLB | AAPL | USD | -554,931.00 | 554,931.00 | PAST_SETTLEMENT | Confirm the direction with the trader and HLB first: the books differ by twice the notional. |
| 4 | SIDE | T000481 | PCM | AAPL | USD | 248,440.04 | 248,440.04 | DUE_NEXT_DAY | Confirm the direction with the trader and PCM first: the books differ by twice the notional. |
| 5 | MISSING | T000489 | HLB | AAPL | USD | -180,582.53 | 180,582.53 | DUE_NEXT_DAY | HLB has no record of this trade: send them the details and confirm it was executed. |
| 6 | MISSING | T000491 | PCM | MSFT | USD | 171,954.40 | 171,954.40 | DUE_NEXT_DAY | PCM has no record of this trade: send them the details and confirm it was executed. |
| 7 | SIDE | T000134 | NGS | XOM | USD | 112,878.64 | 112,878.64 | PAST_SETTLEMENT | Confirm the direction with the trader and NGS first: the books differ by twice the notional. |
| 8 | SETTLE_DATE | T000430 | PCM | 0700.HK | HKD | 0.00 | 106,391.04 | DUE_NEXT_DAY | Ask PCM to amend the settlement date to 2026-11-23; ours matches the calendar. |
| 9 | DUPLICATE | T000103 | NGS | XOM | USD | -95,461.23 | 95,461.23 | PAST_SETTLEMENT | NGS shows this trade twice (statement line 101): ask them to cancel the repeat. |
| 10 | SETTLE_DATE | T000447 | PCM | XOM | USD | 0.00 | 87,837.78 | DUE_TODAY | Ask PCM to amend the settlement date to 2026-11-20; ours matches the calendar. |
| 11 | QUANTITY | T000141 | PCM | AAPL | USD | -65,595.00 | 65,595.00 | PAST_SETTLEMENT | Confirm the filled quantity with PCM: we have 1356, they have 1656. Check for a partial fill. |
| 12 | SETTLE_DATE | T000281 | HLB | XOM | USD | 0.00 | 48,255.51 | PAST_SETTLEMENT | Ask HLB to amend the settlement date to 2026-11-13; ours matches the calendar. |
| 13 | QUANTITY | T000399 | HLB | NVDA | USD | -42,741.00 | 42,741.00 | PAST_SETTLEMENT | Confirm the filled quantity with HLB: we have 139, they have 439. Check for a partial fill. |
| 14 | MISSING | T000151 | HLB | 1299.HK | HKD | -264,122.91 | 33,807.73 | PAST_SETTLEMENT | HLB has no record of this trade: send them the details and confirm it was executed. |
| 15 | SETTLE_DATE | T000406 | PCM | NVDA | USD | 0.00 | 25,415.17 | PAST_SETTLEMENT | Ask PCM to amend the settlement date to 2026-11-19; ours matches the calendar. |

## Notes

- 10 broker lines had no usable trade reference and were paired by symbol, side, quantity and trade date. They are not breaks.
- 0 of our own trades have a settlement date that disagrees with the calendar.
- Impact is the absolute cash difference in USD at a fixed rate. Where no cash is in dispute, it is the trade's notional, marked as notional at risk.
- The full list is in `break_report.csv`.
