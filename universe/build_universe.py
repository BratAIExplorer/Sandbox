"""Clean the raw exchange listing files into scan-ready ticker lists.

Run: python universe/build_universe.py EQUITY_L.csv nasdaqlisted.txt otherlisted.txt
Writes universe/india_all.csv and universe/us_all.csv, plus universe/dropped_*.csv
so every removal can be audited. Read-only on the inputs. No network.
"""
import csv
import re
import sys
from pathlib import Path

OUT = Path(__file__).parent

# Name fragments that mean "not an ordinary operating-company stock".
US_JUNK = re.compile(
    r"\b(warrants?|rights?|units?|preferred|pref|notes?|debentures?|trust preferred|"
    r"acquisition corp|acquisition co|blank check|depositary shares each representing .*preferred|"
    r"subordinated|senior notes|bond|fund|etn)\b",
    re.I,
)


def read_pipe(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f, delimiter="|"))
    # last line is "File Creation Time: ..."
    return [r for r in rows if not (list(r.values())[0] or "").startswith("File Creation Time")]


def build_india(path):
    keep, dropped = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k.strip(): (v or "").strip() for k, v in r.items()}
            row = {"symbol": r["SYMBOL"], "yahoo": r["SYMBOL"] + ".NS", "name": r["NAME OF COMPANY"],
                   "series": r["SERIES"], "listed": r["DATE OF LISTING"], "isin": r["ISIN NUMBER"]}
            if r["SERIES"] == "EQ":
                keep.append(row)
            else:
                row["why"] = f"series {r['SERIES']} (not regular EQ)"
                dropped.append(row)
    return keep, dropped


def yahoo_us(sym):
    return sym.replace(".", "-")


def build_us(nasdaq_path, other_path):
    keep, dropped = [], []

    def judge(sym, name, etf, test, status, exch):
        why = None
        if etf == "Y":
            why = "ETF"
        elif test == "Y":
            why = "test issue"
        elif status not in ("N", ""):
            why = f"financial status {status} (deficient/delinquent/bankrupt)"
        elif "$" in sym or " " in sym:
            why = "preferred/odd symbol"
        elif US_JUNK.search(name):
            why = "warrant/right/unit/preferred/SPAC/note/fund by name"
        row = {"symbol": sym, "yahoo": yahoo_us(sym), "name": name, "exchange": exch}
        if why:
            row["why"] = why
            dropped.append(row)
        else:
            keep.append(row)

    for r in read_pipe(nasdaq_path):
        judge(r["Symbol"], r["Security Name"], r["ETF"], r["Test Issue"], r["Financial Status"], "NASDAQ")
    names = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
    for r in read_pipe(other_path):
        judge(r["ACT Symbol"], r["Security Name"], r["ETF"], r["Test Issue"], "N",
              names.get(r["Exchange"], r["Exchange"]))
    return keep, dropped


def write(name, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main(equity_l, nasdaq, other):
    in_keep, in_drop = build_india(equity_l)
    us_keep, us_drop = build_us(nasdaq, other)
    write("india_all.csv", in_keep)
    write("dropped_india.csv", in_drop)
    write("us_all.csv", us_keep)
    write("dropped_us.csv", us_drop)
    print(f"India: keep {len(in_keep)}, dropped {len(in_drop)}")
    print(f"US:    keep {len(us_keep)}, dropped {len(us_drop)}")
    dup = len(us_keep) - len({r['yahoo'] for r in us_keep})
    print(f"US duplicate Yahoo symbols after cleanup: {dup}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
