"""CANSLIM-style scan for India (NSE) or US. READ-ONLY: fetches data, places no orders.

  python scan/run_scan.py india --limit 40      # small trial first
  python scan/run_scan.py us --min-liq 5000000
A watchlist tool, not a buy list. Output: console table + scan_<market>_<date>.csv.
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import logic  # noqa: E402

MARKETS = {
    "india": dict(file="india_all.csv", index="^CRSLDX", min_liq=50_000_000, cur="Rs"),   # Rs 5 cr/day
    "us": dict(file="us_all.csv", index="^GSPC", min_liq=5_000_000, cur="$"),             # $5M/day
}


def load_universe(market):
    p = Path(__file__).parent.parent / "universe" / MARKETS[market]["file"]
    with open(p, newline="", encoding="utf-8") as f:
        return [(r["yahoo"], r["name"]) for r in csv.DictReader(f)]


def run(market, src, universe, today, near=0.15, min_liq=None, min_mcap=None, limit=None, rules=None, log=print):
    rules = dict(logic.RULES, near_high=near, **(rules or {}))
    cfg = MARKETS[market]
    min_liq = cfg["min_liq"] if min_liq is None else min_liq
    funnel = [("listed (cleaned)", len(universe))]
    if limit:
        universe = universe[:limit]
        funnel.append((f"trial limit", len(universe)))
    names = dict(universe)

    log("Index gate...")
    ix = src.prices([cfg["index"]]).get(cfg["index"])
    if not ix or len(ix["closes"]) < 253:
        gate, ix_ret = dict(status="UNKNOWN (no index data; treated as NO-GO)", above50=None, above200=None, dist=None), None
    else:
        gate, ix_ret = logic.index_gate(ix["closes"], ix["vols"], rules), logic.ret_12m(ix["closes"])

    log("Prices...")
    pr = src.prices([t for t, _ in universe])
    pr = {t: p for t, p in pr.items() if len(p["closes"]) > logic.TRADING_YEAR}
    funnel.append(("has 1y of prices", len(pr)))
    pr = {t: p for t, p in pr.items() if logic.avg_traded_value(p["closes"], p["vols"]) >= min_liq}
    funnel.append((f"liquid (>= {cfg['cur']}{min_liq:,.0f}/day)", len(pr)))

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
        gap = rets[t] - ix_ret if ix_ret is not None else float("nan")
        r = logic.evaluate(stats[t], fund, ranks[t], gap if gap == gap else -9, rules, today)
        r.update(symbol=t, name=fund.get("name") or names[t], sector=fund.get("sector") or "",
                 mcap=fund.get("mcap"), price=round(stats[t]["price"], 2),
                 pct_high=round(stats[t]["pct_high"] * 100), high_date=stats[t]["high_date"].isoformat(),
                 updown=None if stats[t]["updown"] is None else round(stats[t]["updown"], 2),
                 last_bar=stats[t]["last_bar"].isoformat())
        rows.append(r)
        if i % 25 == 0:
            log(f"  {i}/{len(up_set)}")
    funnel.append(("scored", len(rows)))
    if min_mcap:
        rows = [r for r in rows if r["mcap"] and r["mcap"] >= min_mcap]
        funnel.append((f"market cap >= {min_mcap:,.0f}", len(rows)))
    rows.sort(key=lambda r: (r["core_clean"], r["core"], r["tests"], r["rs_rank"]), reverse=True)
    return dict(gate=gate, funnel=funnel, rows=rows, ix_ret=ix_ret)


def show(res, market, today):
    g = res["gate"]
    print(f"\n{market.upper()} scan, {today}")
    print(f"Market gate: {g['status']}. Above 50-day: {g['above50']}. Above 200-day: {g['above200']}. "
          f"Distribution days (25 sessions): {g['dist']} (limit {logic.RULES['dist_limit']}).")
    if not g["status"].startswith("GO"):
        print("Watchlist, not a buy list, while the gate is not GO.")
    print("Funnel: " + " -> ".join(f"{n}: {c}" for n, c in res["funnel"]))
    print("\n*=core (C and A pass), clean=core with no STALE/CHECK/NA flags. Flags need a human look.\n")
    cols = ["symbol", "sector", "core", "C", "A", "N", "S", "L", "I", "pe", "eps_q_yoy", "sales_q_yoy",
            "eps_3y_cagr", "roe", "pct_high", "rs_rank", "latest_q", "next_earnings", "flags"]
    def fmt(k, v):
        if v is None or v == "":
            return "-"
        if k in ("eps_q_yoy", "sales_q_yoy", "eps_3y_cagr", "roe"):
            return f"{v:.0%}"
        if k == "core":
            return "clean*" if v == "clean" else ("*" if v else "")
        if k == "pe":
            return f"{v:.0f}"
        return str(v)
    print("\t".join(cols))
    for r in res["rows"][:60]:
        r = dict(r, core="clean" if r["core_clean"] else r["core"])
        print("\t".join(fmt(k, r.get(k)) for k in cols))


def save(res, market, today):
    out = Path(f"scan_{market}_{today}.csv")
    if res["rows"]:
        keys = list(res["rows"][0].keys())
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(res["rows"])
        print(f"\nSaved {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("market", choices=list(MARKETS))
    ap.add_argument("--near", type=float, default=0.15, help="within this fraction of 52w high (default 0.15)")
    ap.add_argument("--min-liq", type=float, help="min average daily traded value (local currency)")
    ap.add_argument("--min-mcap", type=float, help="min market cap in local currency (India 4,200 cr = 42000000000)")
    ap.add_argument("--limit", type=int, help="only scan the first N tickers (trial run)")
    a = ap.parse_args()
    from data_yf import YFSource
    today = date.today()
    res = run(a.market, YFSource(), load_universe(a.market), today, a.near, a.min_liq, a.min_mcap, a.limit)
    show(res, a.market, today)
    save(res, a.market, today)


if __name__ == "__main__":
    main()
