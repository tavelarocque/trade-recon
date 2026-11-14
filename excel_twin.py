"""Night 7: the Excel twin.

Builds two workbooks from the generated data.

    excel/recon_twin.xlsx   the whole reconciliation done again in Excel
                            formulas, next to the numbers pandas produced,
                            with a check cell that says whether they agree
    excel/practice.xlsx     the same raw data and a list of tasks with
                            targets, and no formulas: yours to build

Nothing here imports the engine. It reads three CSV files, so the Excel
answer is an independent second opinion on the pandas answer.

Run:  python3 report.py      (writes reports/break_report.csv first)
      python3 excel_twin.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config

FONT = "Arial"
BOLD = Font(name=FONT, bold=True)
PLAIN = Font(name=FONT)
INPUT = Font(name=FONT, color="0000FF")          # blue: a typed-in value
LINK = Font(name=FONT, color="008000")           # green: pulled from another sheet
TITLE = Font(name=FONT, bold=True, size=14)
NOTE = Font(name=FONT, italic=True, color="555555")
HEAD_FILL = PatternFill("solid", start_color="DDE5E1")
EDIT_FILL = PatternFill("solid", start_color="FFFF00")  # yellow: a cell for you to edit
MONEY = "#,##0.00;[Red]-#,##0.00"
DATE = "yyyy-mm-dd"

MONTHS = '{"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}'


def parse_date_formula(c: str) -> str:
    """Excel formula turning the broker's text date in cell c into a real date.

    Three formats, told apart by shape: 20261117 has 8 characters,
    2026-11-17 has a dash in position 5, and 17-Nov-2026 is what is left.
    """
    return (f'=IF(LEN({c})=8,DATE(VALUE(LEFT({c},4)),VALUE(MID({c},5,2)),VALUE(RIGHT({c},2))),'
            f'IF(MID({c},5,1)="-",DATE(VALUE(LEFT({c},4)),VALUE(MID({c},6,2)),VALUE(RIGHT({c},2))),'
            f'DATE(VALUE(RIGHT({c},4)),MATCH(MID({c},4,3),{MONTHS},0),VALUE(LEFT({c},2)))))')


def style_header(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font, cell.fill = BOLD, HEAD_FILL
        cell.alignment = Alignment(vertical="top", wrap_text=True)


def set_widths(ws, widths: dict[str, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def font_all(ws) -> None:
    for row in ws.iter_rows():
        for cell in row:
            if cell.font is None or cell.font.name != FONT:
                cell.font = PLAIN


# --------------------------------------------------------------------------- data sheets

def write_internal(ws, internal: pd.DataFrame, with_formulas: bool) -> int:
    cols = ["trade_id", "timestamp", "trade_date", "settle_date", "symbol", "market", "side",
            "quantity", "price", "currency", "venue", "account", "broker", "fees"]
    ws.append(cols + (["our_cash"] if with_formulas else []))
    for r, row in enumerate(internal[cols].itertuples(index=False), start=2):
        ws.append(list(row))
        ws.cell(row=r, column=3).number_format = DATE
        ws.cell(row=r, column=4).number_format = DATE
        ws.cell(row=r, column=9).number_format = "0.00"
        ws.cell(row=r, column=14).number_format = "0.00"
        if with_formulas:
            # Buy is cash out, sell is cash in, fees always out.
            c = ws.cell(row=r, column=15, value=f'=ROUND(IF(G{r}="BUY",-1,1)*H{r}*I{r}-N{r},2)')
            c.number_format = MONEY
    style_header(ws, 1, ws.max_column)
    ws.freeze_panes = "B2"
    set_widths(ws, {"A": 10, "B": 27, "C": 12, "D": 12, "E": 10, "O": 15})
    return len(internal) + 1  # last data row


def write_broker(ws, broker_raw: pd.DataFrame, with_formulas: bool) -> int:
    cols = ["ref", "sym", "bs", "qty", "px", "ccy", "trade_dt", "settle_dt", "comm", "acct", "broker"]
    helpers = ["has_ref", "sym_clean", "side_clean", "trade_clean", "settle_clean", "broker_cash"]
    ws.append(cols + (helpers if with_formulas else []))
    for r, row in enumerate(broker_raw[cols].itertuples(index=False), start=2):
        ref, sym, bs, qty, px, ccy, tdt, sdt, comm, acct, brk = row
        # Text stays text, exactly as the broker sent it. Numbers become numbers.
        ws.append([ref if ref != "" else None, sym, bs, int(qty), float(px), ccy, tdt, sdt, float(comm), acct, brk])
        for c in (1, 2, 7, 8):
            ws.cell(row=r, column=c).number_format = "@"
        ws.cell(row=r, column=5).number_format = "0.00"
        ws.cell(row=r, column=9).number_format = "0.00"
        if with_formulas:
            ws.cell(row=r, column=12, value=f'=IF(A{r}="",0,1)')
            # CLEAN removes the tab characters, TRIM the spaces, UPPER the case.
            ws.cell(row=r, column=13, value=f"=UPPER(TRIM(CLEAN(B{r})))")
            ws.cell(row=r, column=14, value=f'=IF(C{r}="B","BUY","SELL")')
            ws.cell(row=r, column=15, value=parse_date_formula(f"G{r}")).number_format = DATE
            ws.cell(row=r, column=16, value=parse_date_formula(f"H{r}")).number_format = DATE
            ws.cell(row=r, column=17, value=f'=ROUND(IF(C{r}="B",-1,1)*D{r}*E{r}-I{r},2)').number_format = MONEY
    style_header(ws, 1, ws.max_column)
    ws.freeze_panes = "B2"
    set_widths(ws, {"A": 10, "B": 12, "G": 13, "H": 13, "L": 9, "M": 11, "N": 11, "O": 12, "P": 12, "Q": 15})
    return len(broker_raw) + 1


# --------------------------------------------------------------------------- the twin

def build_twin(internal, broker_raw, report, path: Path) -> None:
    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    ws_i = wb.create_sheet("Internal")
    ws_b = wb.create_sheet("Broker")
    ws_r = wb.create_sheet("Recon")
    ws_s = wb.create_sheet("Summary")
    ws_p = wb.create_sheet("Pandas breaks")

    li = write_internal(ws_i, internal, True)   # last row on Internal
    lb = write_broker(ws_b, broker_raw, True)   # last row on Broker

    def B(col: str) -> str:  # an absolute range on the Broker sheet
        return f"Broker!${col}$2:${col}${lb}"

    # ---- Recon: one row per trade of ours, lined up with the Internal sheet
    heads = ["trade_id", "symbol", "currency", "broker", "id_hits", "fallback_hits", "b_side", "b_qty",
             "b_px", "b_fee", "b_settle", "broker_cash", "cash_diff", "break_type", "is_break", "impact_usd"]
    ws_r.append(heads)
    for r in range(2, li + 1):
        fb_criteria = (f"{B('L')},0,{B('M')},B{r},{B('N')},Internal!G{r},"
                       f"{B('D')},Internal!H{r},{B('O')},Internal!C{r}")
        lookup = lambda col: f'=IF(E{r}=0,"",INDEX({B(col)},MATCH(A{r},{B("A")},0)))'
        row = [
            f"=Internal!A{r}", f"=Internal!E{r}", f"=Internal!J{r}", f"=Internal!M{r}",
            f"=COUNTIFS({B('A')},A{r})",                                   # how many broker lines carry our ID
            f"=IF(E{r}=0,COUNTIFS({fb_criteria}),0)",                      # no ID: is there one blank-ref line that fits?
            lookup("N"), lookup("D"), lookup("E"), lookup("I"), lookup("P"),
            f"=SUMIFS({B('Q')},{B('A')},A{r})+IF(F{r}=1,SUMIFS({B('Q')},{fb_criteria}),0)",
            f"=ROUND(Internal!O{r}-L{r},2)",
            (f'=IF(E{r}=0,IF(F{r}=1,"","MISSING"),IF(E{r}>1,"DUPLICATE",'
             f'IF(G{r}<>Internal!G{r},"SIDE",IF(H{r}<>Internal!H{r},"QUANTITY",'
             f'IF(ROUND(I{r}-Internal!I{r},4)<>0,"PRICE",IF(ROUND(J{r}-Internal!N{r},2)<>0,"FEE",'
             f'IF(K{r}<>Internal!D{r},"SETTLE_DATE","")))))))'),
            f'=IF(N{r}="",0,1)',
            (f"=IF(O{r}=0,0,ROUND(ROUND(IF(M{r}<>0,ABS(M{r}),Internal!H{r}*Internal!I{r}),2)"
             f'*IF(C{r}="USD",Summary!$C$5,Summary!$C$6),2))'),
        ]
        ws_r.append(row)
        for c in (1, 2, 3, 4):
            ws_r.cell(row=r, column=c).font = LINK
        ws_r.cell(row=r, column=11).number_format = DATE
        for c in (9, 10):
            ws_r.cell(row=r, column=c).number_format = "0.00"
        for c in (12, 13, 16):
            ws_r.cell(row=r, column=c).number_format = MONEY
    style_header(ws_r, 1, len(heads))
    ws_r.freeze_panes = "B2"
    set_widths(ws_r, {"A": 10, "B": 10, "K": 12, "L": 15, "M": 15, "N": 14, "P": 15})
    ws_r["E1"].comment = Comment("COUNTIFS on the broker's ref column. 0 means no line carries our ID, 2 means a duplicate. "
                                 "XLOOKUP alone would hide a duplicate, because it returns only the first hit.", "trade-recon")
    ws_r["F1"].comment = Comment("The fallback match: for a trade with no ID hit, count broker lines with a blank ref "
                                 "and the same symbol, side, quantity and trade date. Exactly 1 means paired.", "trade-recon")
    ws_r["G1"].comment = Comment("INDEX/MATCH lookup. The Excel 365 equivalent is "
                                 "=XLOOKUP(A2,Broker!$A$2:$A$500,Broker!$N$2:$N$500,\"\")", "trade-recon")
    ws_r["O1"].comment = Comment("A 0/1 flag. Counting breaks with COUNTIFS(range,\"<>\") would be wrong here: "
                                 "a formula that returns \"\" still counts as not empty.", "trade-recon")
    R = lambda col: f"Recon!${col}$2:${col}${li}"

    # ---- Pandas breaks: what the Python engine reported, for comparison only
    pcols = ["rank", "break_type", "trade_id", "broker", "symbol", "currency", "cash_diff", "impact_usd"]
    ws_p.append(pcols)
    for row in report[pcols].itertuples(index=False):
        ws_p.append(list(row))
    for r in range(2, len(report) + 2):
        ws_p.cell(row=r, column=7).number_format = MONEY
        ws_p.cell(row=r, column=8).number_format = MONEY
    style_header(ws_p, 1, len(pcols))
    set_widths(ws_p, {"B": 14, "G": 15, "H": 15})

    # ---- Summary
    s = ws_s
    s["A1"], s["A1"].font = "Excel twin: does the spreadsheet agree with pandas?", TITLE
    s["A2"], s["A2"].font = "Left columns are Excel formulas over the raw sheets. Right columns are the numbers the Python engine reported.", NOTE

    s["A4"], s["A4"].font = "Assumptions", BOLD
    s["B5"], s["C5"] = "USD per 1 USD", config.USD_PER["USD"]
    s["B6"], s["C6"] = "USD per 1 HKD", config.USD_PER["HKD"]
    s["C5"].font = s["C6"].font = INPUT
    s["D6"], s["D6"].font = "Fixed rate from config.py, used for ranking only. HKD is pegged near 7.8 per USD.", NOTE

    # totals check
    s["A8"], s["A8"].font = "Totals check, local currency", BOLD
    hdr = ["currency", "our cash", "broker cash", "gap", "sum of Excel breaks", "unexplained", "ok"]
    for c, h in enumerate(hdr, start=1):
        s.cell(row=9, column=c, value=h)
    style_header(s, 9, len(hdr))
    for i, ccy in enumerate(["HKD", "USD"]):
        r = 10 + i
        s.cell(row=r, column=1, value=ccy)
        s.cell(row=r, column=2, value=f"=SUMIFS(Internal!$O$2:$O${li},Internal!$J$2:$J${li},A{r})")
        s.cell(row=r, column=3, value=f"=SUMIFS({B('Q')},{B('F')},A{r})")
        s.cell(row=r, column=4, value=f"=ROUND(B{r}-C{r},2)")
        s.cell(row=r, column=5, value=f"=SUMIFS({R('M')},{R('C')},A{r})")
        s.cell(row=r, column=6, value=f"=ROUND(D{r}-E{r},2)")
        s.cell(row=r, column=7, value=f"=F{r}=0")
        for c in range(2, 7):
            s.cell(row=r, column=c).number_format = MONEY

    # by type
    types = report.groupby("break_type").agg(count=("rank", "size"), impact=("impact_usd", "sum")).round(2)
    types = types.sort_values("impact", ascending=False)
    s["A13"], s["A13"].font = "By break type", BOLD
    hdr = ["break type", "Excel count", "pandas count", "Excel impact USD", "pandas impact USD", "ok"]
    for c, h in enumerate(hdr, start=1):
        s.cell(row=14, column=c, value=h)
    style_header(s, 14, len(hdr))
    r = 15
    first_type = r
    for name, row in types.iterrows():
        s.cell(row=r, column=1, value=name)
        s.cell(row=r, column=2, value=f"=COUNTIFS({R('N')},A{r})")
        s.cell(row=r, column=3, value=int(row["count"])).font = INPUT
        s.cell(row=r, column=4, value=f"=SUMIFS({R('P')},{R('N')},A{r})").number_format = MONEY
        s.cell(row=r, column=5, value=float(row["impact"])).font = INPUT
        s.cell(row=r, column=5).number_format = MONEY
        s.cell(row=r, column=6, value=f"=AND(B{r}=C{r},ROUND(D{r}-E{r},2)=0)")
        r += 1
    last_type = r - 1
    s.cell(row=r, column=1, value="Total").font = BOLD
    s.cell(row=r, column=2, value=f"=SUM(B{first_type}:B{last_type})")
    s.cell(row=r, column=3, value=f"=SUM(C{first_type}:C{last_type})")
    s.cell(row=r, column=4, value=f"=SUM(D{first_type}:D{last_type})").number_format = MONEY
    s.cell(row=r, column=5, value=f"=SUM(E{first_type}:E{last_type})").number_format = MONEY
    s.cell(row=r, column=6, value=f"=AND(B{r}=SUM({R('O')}),B{r}=C{r},ROUND(D{r}-E{r},2)=0)")
    total_row = r

    # by broker
    brokers = report.groupby("broker").agg(count=("rank", "size"), impact=("impact_usd", "sum")).round(2)
    brokers = brokers.sort_values("impact", ascending=False)
    r += 2
    s.cell(row=r, column=1, value="By broker").font = BOLD
    r += 1
    hdr = ["broker", "Excel count", "pandas count", "Excel impact USD", "pandas impact USD", "ok"]
    for c, h in enumerate(hdr, start=1):
        s.cell(row=r, column=c, value=h)
    style_header(s, r, len(hdr))
    r += 1
    first_broker = r
    for name, row in brokers.iterrows():
        s.cell(row=r, column=1, value=name)
        s.cell(row=r, column=2, value=f"=SUMIFS({R('O')},{R('D')},A{r})")
        s.cell(row=r, column=3, value=int(row["count"])).font = INPUT
        s.cell(row=r, column=4, value=f"=SUMIFS({R('P')},{R('D')},A{r})").number_format = MONEY
        s.cell(row=r, column=5, value=float(row["impact"])).font = INPUT
        s.cell(row=r, column=5).number_format = MONEY
        s.cell(row=r, column=6, value=f"=AND(B{r}=C{r},ROUND(D{r}-E{r},2)=0)")
        r += 1
    last_broker = r - 1

    # verdict
    r += 1
    s.cell(row=r, column=1, value="Every check passes").font = BOLD
    s.cell(row=r, column=2, value=f"=AND(G10,G11,AND(F{first_type}:F{total_row}),AND(F{first_broker}:F{last_broker}))").font = BOLD
    verdict_row = r

    # lookup panel
    r += 2
    s.cell(row=r, column=1, value="Look up one trade").font = BOLD
    s.cell(row=r + 1, column=1, value="trade_id")
    s.cell(row=r + 1, column=2, value=str(report.loc[report["break_type"] == "PRICE", "trade_id"].iloc[0]))
    s.cell(row=r + 1, column=2).fill = EDIT_FILL
    s.cell(row=r + 1, column=3, value="Type any trade_id in the yellow cell.").font = NOTE
    items = [("our price", f"=INDEX(Internal!$I$2:$I${li},MATCH($B${r+1},Internal!$A$2:$A${li},0))",
              f"=XLOOKUP($B${r+1},Internal!$A$2:$A${li},Internal!$I$2:$I${li})"),
             ("broker price", f'=IFERROR(INDEX({B("E")},MATCH($B${r+1},{B("A")},0)),"not found")',
              f'=XLOOKUP($B${r+1},{B("A")},{B("E")},"not found")'),
             ("break type", f"=INDEX({R('N')},MATCH($B${r+1},{R('A')},0))", f"=XLOOKUP($B${r+1},{R('A')},{R('N')})"),
             ("cash difference", f"=INDEX({R('M')},MATCH($B${r+1},{R('A')},0))", f"=XLOOKUP($B${r+1},{R('A')},{R('M')})")]
    s.cell(row=r + 2, column=3, value="The same lookup written with XLOOKUP, for you to type yourself:").font = NOTE
    for k, (label, formula, xl) in enumerate(items):
        rr = r + 3 + k
        s.cell(row=rr, column=1, value=label)
        s.cell(row=rr, column=2, value=formula)
        shown = s.cell(row=rr, column=3, value=xl)
        shown.data_type = "s"  # stored as text, so it is displayed and not run
        shown.font = NOTE
        if "price" in label or "cash" in label:
            s.cell(row=rr, column=2).number_format = MONEY
    set_widths(s, {"A": 22, "B": 18, "C": 18, "D": 20, "E": 20, "F": 14, "G": 8})

    # ---- Read me
    lines = [
        ("Excel twin of the trade-recon project", TITLE),
        ("", PLAIN),
        ("What this is", BOLD),
        ("The reconciliation done a second time, in Excel formulas only, on the same two files the Python engine reads.", PLAIN),
        (f"The Summary sheet compares the two answers. Cell B{verdict_row} there is TRUE when every number agrees to the cent.", PLAIN),
        ("", PLAIN),
        ("Sheets", BOLD),
        ("Internal: our blotter. Column O is the signed cash of each trade.", PLAIN),
        ("Broker: the broker's statement exactly as sent, mess included. Columns L to Q clean it up.", PLAIN),
        ("Recon: one row per trade of ours. Finds the broker's line, compares it, names the break, sizes it.", PLAIN),
        ("Summary: totals check, counts and impact by break type and by broker, and a lookup panel.", PLAIN),
        ("Pandas breaks: the break list the Python engine reported. Values, not formulas. For comparison only.", PLAIN),
        ("", PLAIN),
        ("Colours", BOLD),
        ("Blue text is a typed-in value. Black is a formula. Green is a value pulled from another sheet. Yellow fill is a cell for you to edit.", PLAIN),
        ("", PLAIN),
        ("Known limits", BOLD),
        ("The Excel break_type formula names one break per trade, checked in a fixed order. The Python engine also reports several wrong fields on one trade.", PLAIN),
        ("A trade paired by the fallback is not compared field by field here. The generator only blanks the reference of otherwise clean trades.", PLAIN),
        ("Lookups use INDEX and MATCH so the file opens in any spreadsheet program. The XLOOKUP form of each is shown on the Summary sheet.", PLAIN),
        ("There is no pivot table in this file. Building one on the Recon sheet is one of your tasks: rows break_type, values count of is_break and sum of impact_usd.", PLAIN),
    ]
    for i, (text, font) in enumerate(lines, start=1):
        c = readme.cell(row=i, column=1, value=text)
        c.font = font
    readme.column_dimensions["A"].width = 130

    for ws in (ws_i, ws_b, ws_r, ws_p, ws_s, readme):
        font_all(ws)
    wb.move_sheet("Summary", offset=-(wb.index(ws_s) - 1))  # Summary right after Read me
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------- practice file

def build_practice(internal, broker_raw, report, path: Path) -> None:
    wb = Workbook()
    tasks = wb.active
    tasks.title = "Tasks"
    ws_i = wb.create_sheet("Internal")
    ws_b = wb.create_sheet("Broker")
    li = write_internal(ws_i, internal, False)
    lb = write_broker(ws_b, broker_raw, False)

    sign = internal["side"].map({"BUY": -1, "SELL": 1})
    our_cash = (sign * internal["quantity"] * internal["price"] - internal["fees"]).round(2)
    bsign = broker_raw["bs"].map({"B": -1, "S": 1})
    brk_cash = (bsign * broker_raw["qty"].astype(int) * broker_raw["px"].astype(float) - broker_raw["comm"].astype(float)).round(2)
    usd_i, usd_b = internal["currency"] == "USD", broker_raw["ccy"] == "USD"
    refs = broker_raw.loc[broker_raw["ref"] != "", "ref"]
    counts = refs.value_counts()

    rows = [
        # (task, hint, target, number format)
        ("Our total cash in USD. Buy is cash out, sell is cash in, fees always out.",
         "SUMPRODUCT, or add a cash column and use SUMIFS.", round(float(our_cash[usd_i].sum()), 2), MONEY),
        ("The broker's total cash in USD, from their own columns.",
         "Their side codes are B and S.", round(float(brk_cash[usd_b].sum()), 2), MONEY),
        ("The gap in USD: ours minus theirs.", "One subtraction. Round to cents.",
         round(float(our_cash[usd_i].sum()) - float(brk_cash[usd_b].sum()), 2), MONEY),
        ("How many of our trade IDs appear nowhere in the broker's ref column?",
         "XLOOKUP with a not-found value, or COUNTIFS equal to 0.", int((~internal["trade_id"].isin(refs)).sum()), "0"),
        ("How many different IDs appear more than once in the broker's ref column?",
         "COUNTIFS. XLOOKUP cannot see this.", int((counts > 1).sum()), "0"),
        ("How many broker lines have a blank ref?", "COUNTBLANK.", int((broker_raw["ref"] == "").sum()), "0"),
        ("How many broker lines have a sym that is not already clean upper-case text?",
         "Compare sym with UPPER(TRIM(CLEAN(sym))) using EXACT.",
         int((broker_raw["sym"] != broker_raw["sym"].str.strip().str.upper()).sum()), "0"),
        ("How many broker lines write settle_dt as 8 digits, like 20261117?",
         "LEN. Then parse them with DATE, LEFT, MID and RIGHT.", int((broker_raw["settle_dt"].str.len() == 8).sum()), "0"),
        ("Among trades found by ID exactly once, how many have a broker price different from ours?",
         "Look up px, subtract, ROUND to 4 places before comparing.", int((report["break_type"] == "PRICE").sum()), "0"),
        ("Total impact in USD of every break, at 0.128 USD per HKD.",
         "The full reconciliation. See the Recon sheet of recon_twin.xlsx only after you have tried.",
         round(float(report["impact_usd"].sum()), 2), MONEY),
        ("The T+1 settlement date of a US trade done on 10 November 2026.",
         "WORKDAY with a holiday list. 11 November is Veterans Day: the market trades and nothing settles.",
         date(2026, 11, 12), DATE),
    ]

    tasks["A1"], tasks["A1"].font = "Practice tasks", TITLE
    tasks["A2"] = ("Build each answer with formulas on the Internal and Broker sheets. Type or build your answer in the yellow cell. "
                   "The check cell turns TRUE when it matches the target to the cent.")
    tasks["A2"].font = NOTE
    tasks["A3"] = "Time yourself. The real test is graded on exact answers, so check each one a second way before you move on."
    tasks["A3"].font = NOTE
    for c, h in enumerate(["#", "task", "hint", "your answer", "target", "check"], start=1):
        tasks.cell(row=5, column=c, value=h)
    style_header(tasks, 5, 6)

    # one worked example so the format is clear
    tasks.append(["ex", "Example: how many trades are on our blotter?", "COUNTA on the trade_id column.",
                  f"=COUNTA(Internal!A2:A{li})", len(internal), None])
    tasks["F6"] = '=IF(D6="","",ROUND(D6-E6,2)=0)'
    tasks["E6"].font = INPUT

    for n, (task, hint, target, fmt) in enumerate(rows, start=1):
        r = 6 + n
        tasks.cell(row=r, column=1, value=n)
        tasks.cell(row=r, column=2, value=task)
        tasks.cell(row=r, column=3, value=hint)
        tasks.cell(row=r, column=4).fill = EDIT_FILL
        tasks.cell(row=r, column=4).number_format = fmt
        t = tasks.cell(row=r, column=5, value=target)
        t.font, t.number_format = INPUT, fmt
        tasks.cell(row=r, column=6, value=f'=IF(D{r}="","",ROUND(D{r}-E{r},2)=0)')
    last = 6 + len(rows)
    tasks.cell(row=last + 2, column=2, value="Tasks correct").font = BOLD
    tasks.cell(row=last + 2, column=4, value=f"=COUNTIF(F7:F{last},TRUE)")
    tasks.cell(row=last + 2, column=5, value=len(rows)).font = INPUT
    tasks.cell(row=last + 4, column=2, value="Targets were computed by the Python engine from the same data (seed 42).").font = NOTE
    tasks.cell(row=last + 5, column=2, value="Then build a pivot table on a sheet of your own: break type in rows, count and sum of impact in values.").font = NOTE
    for r in range(6, last + 1):
        for c in (2, 3):
            tasks.cell(row=r, column=c).alignment = Alignment(wrap_text=True, vertical="top")
    set_widths(tasks, {"A": 5, "B": 62, "C": 50, "D": 18, "E": 18, "F": 9})

    for ws in (tasks, ws_i, ws_b):
        font_all(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> None:
    internal = pd.read_csv("data/internal_blotter.csv")
    for col in ("trade_date", "settle_date"):
        internal[col] = pd.to_datetime(internal[col]).dt.date
    # The broker file is read as text, so the mess survives into the workbook.
    broker_raw = pd.read_csv("data/broker_statement.csv", dtype=str, keep_default_na=False)
    report = pd.read_csv("reports/break_report.csv")

    build_twin(internal, broker_raw, report, Path("excel/recon_twin.xlsx"))
    build_practice(internal, broker_raw, report, Path("excel/practice.xlsx"))
    print("wrote excel/recon_twin.xlsx and excel/practice.xlsx")


if __name__ == "__main__":
    main()
