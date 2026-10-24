"""CANSLIM-style scan: india, us, malaysia, japan, euronext. READ-ONLY: fetches data, places no orders.

  python scan/run_scan.py india --limit 40                 # small trial first
  python scan/run_scan.py us --bucket large mid
  python scan/run_scan.py japan --min-liq 1000000          # min avg daily traded value, in USD
A watchlist tool, not a buy list. Output: console table + scan_<market>_<date>.csv.
Each market uses its own index for the gate and for relative strength.
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import logic  # noqa: E402

# min_liq is US$ per day (about half a million: small caps and pennies still get in, dead stocks do not).
MARKETS = {
    "india": dict(file="india_all.csv", index="^CRSLDX", cur="INR", min_liq=500_000),
    "us": dict(file="us_all.csv", index="^GSPC", cur="USD", min_liq=500_000),
    "malaysia": dict(file="malaysia_all.csv", index="^KLSE", cur="MYR", min_liq=500_000),
    "japan": dict(file="japan_all.csv", index="^N225", cur="JPY", min_liq=500_000),   # Nikkei 225 as the gate index
    "euronext": dict(file="euronext_all.csv", index="^N100", cur="EUR", min_liq=500_000),  # Euronext 100
}


def load_universe(market):
    """[(yahoo symbol, name, currency)]"""
    p = Path(__file__).parent.parent / "universe" / MARKETS[market]["file"]
    with open(p, newline="", encoding="utf-8") as f:
        return [(r["yahoo"], r["name"], r.get("currency") or MARKETS[market]["cur"]) for r in csv.DictReader(f)]


def get_fx(src, currencies):
    """Local units per 1 USD, from Yahoo 'XXX=X' pairs. Missing -> absent (those stocks are skipped, never guessed)."""
    fx = {"USD": 1.0}
    need = sorted(c for c in set(currencies) if c and c != "USD")
    got = src.prices([f"{c}=X" for c in need]) if need else {}
    for c in need:
        p = got.get(f"{c}=X")
        if p and p["closes"] and p["closes"][-1] > 0:
            fx[c] = p["closes"][-1]
    return fx


def run(market, src, universe, today, near=0.15, min_liq=None, min_mcap=None, limit=None, rules=None, log=print,
        buckets=None):
    rules = dict(logic.RULES, near_high=near, **(rules or {}))
    cfg = MARKETS[market]
    min_liq = cfg["min_liq"] if min_liq is None else min_liq
    funnel = [("listed (cleaned)", len(universe))]
    if limit:
        universe = universe[:limit]
        funnel.append((f"trial limit", len(universe)))
    names = {t: n for t, n, _ in universe}
    cur = {t: c for t, _, c in universe}
    fx = get_fx(src, cur.values())
    skipped = sorted({c for c in cur.values() if c not in fx})
    if skipped:
        log(f"No FX rate for {skipped}: those stocks are skipped (not guessed).")

    log("Index gate...")
    ix = src.prices([cfg["index"]]).get(cfg["index"])
    if not ix or len(ix["closes"]) < 253:
        gate, ix_ret = dict(status="UNKNOWN (no index data; treated as NO-GO)", above50=None, above200=None, dist=None), None
    else:
        gate, ix_ret = logic.index_gate(ix["closes"], ix["vols"], rules), logic.ret_12m(ix["closes"])

    log("Prices...")
    pr = src.prices([t for t, _, _ in universe if cur[t] in fx])
    pr = {t: p for t, p in pr.items() if len(p["closes"]) > logic.TRADING_YEAR}
    funnel.append(("has 1y of prices", len(pr)))
    pr = {t: p for t, p in pr.items() if logic.avg_traded_value(p["closes"], p["vols"]) / fx[cur[t]] >= min_liq}
    funnel.append((f"liquid (>= US${min_liq:,.0f}/day)", len(pr)))

    rets = {t: logic.ret_12m(p["closes"]) for t, p in pr.items()}
    ranks = logic.rs_ranks(rets)
    stats = {}
    for t, p in pr.items():
        ph, hd = logic.pct_of_high(p["closes"], p["dates"])
        stats[t] = dict(pct_high=ph, high_date=hd, price=p["closes"][-1],
                        updown=logic.updown_ratio(p["closes"], p["vols"]),
                        big_down=logic.big_down_recent(p["closes"], p["vols"]),
                        last_bar=p["dates"][-1])
    near_set = [t for t in pr if stats[t]["pct_high"] >= 1 - near]
    funnel.append((f"within {near:.0%} of 52w closing high", len(near_set)))
    up_set = [t for t in near_set if rets[t] > 0]
    funnel.append(("up over 12 months", len(up_set)))

    log(f"Fundamentals for {len(up_set)} stocks (slow part)...")
    rows = []
    for i, t in enumerate(up_set, 1):
        fund = src.fundamentals(t)
        if not fund:
            continue
        gap = rets[t] - ix_ret if ix_ret is not None else None
        r = logic.evaluate(stats[t], fund, ranks[t], gap, rules, today)
        r.update(symbol=t, name=fund.get("name") or names[t], sector=fund.get("sector") or "",
                 mcap=fund.get("mcap"), currency=cur[t], price=round(stats[t]["price"], 2),
                 pct_high=stats[t]["pct_high"], high_date=stats[t]["high_date"].isoformat(),
                 updown=None if stats[t]["updown"] is None else round(stats[t]["updown"], 2),
                 last_bar=stats[t]["last_bar"].isoformat())
        mc = fund.get("mcap")
        if mc is None and fund.get("shares_out"):
            mc = stats[t]["price"] * fund["shares_out"]     # Yahoo had no market cap: price x shares outstanding
            r["flags"] = (r["flags"] + "; " if r["flags"] else "") + "MCAP-CALC(Yahoo had none)"
            r["mcap"] = mc
        r["mcap_usd_m"] = round(mc / fx[cur[t]] / 1e6) if mc else None
        r["price_usd"] = round(stats[t]["price"] / fx[cur[t]], 2)
        r["bucket"] = logic.size_bucket(mc / fx[cur[t]] if mc else None, stats[t]["price"] / fx[cur[t]])
        if r["bucket"] == "penny":
            r["flags"] = (r["flags"] + "; " if r["flags"] else "") + "PENNY(thin, high risk)"
        rows.append(r)
        if i % 25 == 0:
            log(f"  {i}/{len(up_set)}")
    funnel.append(("scored", len(rows)))
    if min_mcap:
        rows = [r for r in rows if r["mcap"] and r["mcap"] >= min_mcap]
        funnel.append((f"market cap >= {min_mcap:,.0f}", len(rows)))
    if buckets:
        rows = [r for r in rows if r["bucket"] in buckets]
        funnel.append((f"size bucket in {sorted(buckets)}", len(rows)))
    rows.sort(key=lambda r: (r["core_clean"], r["core"], r["tests"], r["rs_rank"]), reverse=True)
    return dict(gate=gate, funnel=funnel, rows=rows, ix_ret=ix_ret)


# (key, header). Headers for the 14 requested fields are exactly as requested.
COLS = [("symbol", "Symbol"), ("name", "Name"), ("bucket", "Size"), ("sector", "Sector"), ("core", "Core"),
        ("C", "C"), ("A", "A"), ("N", "N"), ("S", "S"), ("L", "L"), ("I", "I"),
        ("mcap", "Mkt cap"), ("currency", "Cur"), ("price", "Price"), ("pe", "P/E"), ("latest_q", "Latest qtr"),
        ("eps_q_yoy", "EPS qtr YoY"), ("sales_q_yoy", "Sales qtr YoY"), ("eps_3y_cagr", "EPS 3y CAGR"),
        ("roe", "ROE"), ("pct_high", "Close vs 52w-high close"), ("high_date", "High date"),
        ("rs_gap", "RS gap"), ("rs_rank", "RS rank"), ("updown", "Up/down vol"), ("shares_yoy", "Shares YoY"),
        ("mcap_usd_m", "Mkt cap US$m"), ("price_usd", "Price US$"), ("next_earnings", "Next results"),
        ("flags", "Flags")]
PCT = {"eps_q_yoy", "sales_q_yoy", "eps_3y_cagr", "roe", "pct_high", "rs_gap", "shares_yoy"}


def fmt(k, v, console=False):
    if v is None or v == "":
        return "-" if console else ""
    if k == "core":
        return "clean*" if v == "clean" else ("*" if v else "")
    if k in PCT:
        return f"{v:.0%}" if k != "rs_gap" else f"{v * 100:+.0f}pts"
    if k == "mcap":
        return f"{v / 1e9:,.1f}B" if v >= 1e9 else f"{v / 1e6:,.0f}M"
    if k in ("pe", "updown"):
        return f"{v:.0f}" if k == "pe" else f"{v:.2f}"
    return str(v)


def show(res, market, today):
    g = res["gate"]
    print(f"\n{market.upper()} scan, {today}")
    print(f"Market gate: {g['status']}. Above 50-day: {g['above50']}. Above 200-day: {g['above200']}. "
          f"Distribution days (25 sessions): {g['dist']} (limit {logic.RULES['dist_limit']}).")
    if not g["status"].startswith("GO"):
        print("Watchlist, not a buy list, while the gate is not GO.")
    print("Funnel: " + " -> ".join(f"{n}: {c}" for n, c in res["funnel"]))
    print("\n*=core (C and A pass), clean*=core with no STALE/CHECK/NA/FROM-VENDOR flags. Flags need a human look.\n")
    print("\t".join(h for _, h in COLS))
    for r in res["rows"][:60]:
        r = dict(r, core="clean" if r["core_clean"] else r["core"])
        print("\t".join(fmt(k, r.get(k), True) for k, _ in COLS))


def save(res, market, today):
    out = Path(f"scan_{market}_{today}.csv")
    if res["rows"]:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([h for _, h in COLS])
            for r in res["rows"]:
                r = dict(r, core="clean" if r["core_clean"] else r["core"])
                w.writerow([fmt(k, r.get(k)) for k, _ in COLS])
        print(f"\nSaved {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("market", choices=list(MARKETS))
    ap.add_argument("--near", type=float, default=0.15, help="within this fraction of 52w high (default 0.15)")
    ap.add_argument("--min-liq", type=float, help="min average daily traded value in US$ (default 500000)")
    ap.add_argument("--bucket", nargs="+", choices=["large", "mid", "small", "penny"], help="keep only these size buckets")
    ap.add_argument("--min-mcap", type=float, help="min market cap in local currency (India 4,200 cr = 42000000000)")
    ap.add_argument("--limit", type=int, help="only scan the first N tickers (trial run)")
    a = ap.parse_args()
    from data_yf import YFSource
    today = date.today()
    res = run(a.market, YFSource(), load_universe(a.market), today, a.near, a.min_liq, a.min_mcap, a.limit, buckets=a.bucket)
    show(res, a.market, today)
    save(res, a.market, today)


if __name__ == "__main__":
    main()
