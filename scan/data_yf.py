"""Yahoo Finance data layer (via the yfinance package). Read-only, places no orders.

Setup on your PC:  pip install yfinance pandas
Everything vendor-specific lives here so scan rules stay testable. Yahoo fundamentals are
a free scrape: treat every number as unverified until compared with the company filing.
"""
import json
import time
from datetime import date, datetime
from pathlib import Path


def _yf():
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        raise SystemExit("Run first:  pip install yfinance pandas")
    return yf, pd


def _num(x):
    try:
        x = float(x)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _row(df, names):
    """First matching row of a statement as a newest-first list, plus its dates."""
    if df is None or getattr(df, "empty", True):
        return [], []
    cols = sorted(df.columns, reverse=True)
    for n in names:
        if n in df.index:
            return [_num(df.loc[n, c]) for c in cols], [c.date() for c in cols]
    return [], [c.date() for c in cols]


class YFSource:
    def __init__(self, cache_dir=".scan_cache", pause=0.4):
        self.yf, self.pd = _yf()
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.pause = pause

    def prices(self, tickers, chunk=100):
        """{ticker: dict(dates, closes, vols)} for tickers Yahoo returned data for."""
        out = {}
        for i in range(0, len(tickers), chunk):
            part = tickers[i:i + chunk]
            try:
                df = self.yf.download(part, period="14mo", interval="1d", auto_adjust=True,
                                      group_by="ticker", threads=True, progress=False)
            except Exception as e:
                print(f"  price batch {i} failed: {type(e).__name__}: {e}")
                continue
            for t in part:
                try:
                    sub = df[t] if isinstance(df.columns, self.pd.MultiIndex) else df
                    sub = sub[["Close", "Volume"]].dropna(subset=["Close"])
                except KeyError:
                    continue
                if len(sub):
                    out[t] = dict(dates=[d.date() for d in sub.index],
                                  closes=[float(x) for x in sub["Close"]],
                                  vols=[float(x or 0) for x in sub["Volume"]])
            print(f"  prices {min(i + chunk, len(tickers))}/{len(tickers)}", end="\r")
        print()
        return out

    def fundamentals(self, sym):
        f = self.cache / f"{sym.replace('^', '_')}.json"
        if f.exists() and time.time() - f.stat().st_mtime < 86400:
            return _revive(json.loads(f.read_text()))
        for attempt in range(3):
            try:
                d = self._fetch(sym)
                f.write_text(json.dumps(d, default=str))
                time.sleep(self.pause)
                return d
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
                time.sleep(2 ** attempt)
        print(f"  fundamentals failed for {sym}: {last}")
        return {}

    def _fetch(self, sym):
        t = self.yf.Ticker(sym)
        info = t.info or {}
        q = t.quarterly_income_stmt
        eps_q, qdates = _row(q, ["Diluted EPS", "Basic EPS"])
        rev_q, _ = _row(q, ["Total Revenue", "Operating Revenue"])
        ni_q, _ = _row(q, ["Net Income", "Net Income Common Stockholders"])
        eps_a, _ = _row(t.income_stmt, ["Diluted EPS", "Basic EPS"])
        last_rep = next_e = None
        try:
            ed = t.get_earnings_dates(limit=12)
            now = self.pd.Timestamp.now(tz=ed.index.tz)
            past = ed[ed["Reported EPS"].notna() & (ed.index <= now)]
            fut = ed[ed.index > now]
            last_rep = past.index.max().date() if len(past) else None
            next_e = fut.index.min().date() if len(fut) else None
        except Exception:
            pass
        return dict(
            name=info.get("shortName") or info.get("longName") or sym,
            sector=info.get("sector"), industry=info.get("industry"),
            mcap=_num(info.get("marketCap")), pe=_num(info.get("trailingPE")),
            pb=_num(info.get("priceToBook")), inst=_num(info.get("heldPercentInstitutions")),
            roe=_num(info.get("returnOnEquity")),
            eps_q=eps_q, rev_q=rev_q, ni_q=ni_q, qdates=qdates, eps_a=eps_a,
            vendor_rev_g=_num(info.get("revenueGrowth")),
            vendor_ni_g=_num(info.get("earningsQuarterlyGrowth")),
            last_reported=last_rep, next_earnings=next_e,
        )


def _revive(d):
    """JSON cache stores dates as text; turn them back into date objects."""
    for k in ("last_reported", "next_earnings"):
        if d.get(k):
            d[k] = datetime.strptime(d[k][:10], "%Y-%m-%d").date()
    d["qdates"] = [datetime.strptime(x[:10], "%Y-%m-%d").date() for x in d.get("qdates", [])]
    return d
