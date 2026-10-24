"""Build ticker lists for Malaysia (Bursa), Japan (Tokyo) and Euronext from Yahoo's equity screener.

Run: python universe/build_global.py            (needs network + `pip install yfinance`)
Writes universe/malaysia_all.csv, japan_all.csv, euronext_all.csv (+ dropped_<market>.csv).
Yahoo's list is a convenience scrape, not the official exchange file: counts can differ from the
exchange. Read-only, places no orders.
"""
import csv
import re
import time
from pathlib import Path

import yfinance as yf
from yfinance import EquityQuery as Q

OUT = Path(__file__).parent
MARKETS = {
    "malaysia": ["KLS"],
    "japan": ["JPX"],
    "euronext": ["PAR", "AMS", "BRU", "LIS", "ISE", "MIL", "OSL"],
}
# warrants / rights / preference / structured paper that slip into equity lists
JUNK_NAME = re.compile(r"\b(warrants?|rights?|preference|preferred|loan stock|redeemable|etf|etn|reit)\b", re.I)


def junk(sym, name):
    base = sym.split(".")[0]
    if re.search(r"-[A-Z]{1,2}$", base) and sym.endswith(".KL"):   # Bursa warrant/ICPS suffix
        return "Bursa warrant/loan-stock suffix"
    if JUNK_NAME.search(name or ""):
        return "warrant/right/preference/ETF/REIT by name"
    return None


def pull(exchanges):
    q = Q("is-in", ["exchange", *exchanges]) if len(exchanges) > 1 else Q("eq", ["exchange", exchanges[0]])
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        for attempt in range(4):
            try:
                r = yf.screen(q, size=250, offset=offset, sortField="intradaymarketcap", sortAsc=False)
                break
            except Exception as e:
                print(f"   retry {attempt}: {type(e).__name__}: {e}")
                time.sleep(2 ** attempt)
        else:
            print("   giving up at offset", offset)
            break
        total = r.get("total", 0)
        quotes = r.get("quotes", [])
        if not quotes:
            break
        rows += quotes
        offset += len(quotes)
        time.sleep(0.5)
    return rows, total


def main():
    for market, exch in MARKETS.items():
        rows, total = pull(exch)
        keep, drop, seen = [], [], set()
        for x in rows:
            sym = x["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            row = dict(symbol=sym, yahoo=sym, name=x.get("shortName") or x.get("longName") or "",
                       exchange=x.get("exchange", ""), currency=x.get("currency", ""),
                       mcap=x.get("marketCap") or "", price=x.get("regularMarketPrice") or "")
            why = "no market cap on Yahoo (bond/certificate/delisted)" if not row["mcap"] else junk(sym, row["name"])
            if why:
                row["why"] = why
                drop.append(row)
            else:
                keep.append(row)
        for name, data in ((f"{market}_all.csv", keep), (f"dropped_{market}.csv", drop)):
            if data:
                with open(OUT / name, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                    w.writeheader()
                    w.writerows(data)
        print(f"{market}: Yahoo total {total}, pulled {len(rows)}, keep {len(keep)}, dropped {len(drop)}")


if __name__ == "__main__":
    main()
