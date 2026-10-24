"""Pure scan rules: lists in, numbers out. No network, no pandas, places no orders.

Price lists run oldest -> newest. Quarterly / annual lists run newest -> oldest.
Thresholds in RULES were INFERRED from the pass/fail pattern of the earlier screen
(not from its code). Edit them here if they are wrong.
"""
from datetime import timedelta

TRADING_YEAR = 252

RULES = dict(
    eps_q_yoy=0.20,     # C: latest-quarter EPS growth vs same quarter last year
    sales_q_yoy=0.20,   # C: same for sales
    eps_3y_cagr=0.25,   # A: 3-year EPS growth per year
    roe=0.175,          # A: return on equity
    near_high=0.15,     # N: within this fraction of the 52-week closing high
    rs_gap=0.10,        # L: beat the index by this much over 12 months
    updown=1.0,         # S: 50-day up-volume / down-volume
    inst=0.10,          # I: institutional holding fraction (weak data, esp. India)
    dist_limit=4,       # gate: max distribution days in window
    dist_window=25,
)


def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def pct_of_high(closes, dates):
    """Last close / highest close of the last 252 sessions, and the date of that high."""
    w = closes[-TRADING_YEAR:]
    hi = max(w)
    d = dates[-len(w):][w.index(hi)]
    return closes[-1] / hi, d


def ret_12m(closes):
    return closes[-1] / closes[-(TRADING_YEAR + 1)] - 1 if len(closes) > TRADING_YEAR else None


def avg_traded_value(closes, vols, n=50):
    k = min(n, len(closes))
    return sum(c * v for c, v in zip(closes[-k:], vols[-k:])) / k if k else 0.0


def updown_ratio(closes, vols, n=50):
    up = dn = 0.0
    for i in range(len(closes) - n, len(closes)):
        if i < 1:
            continue
        if closes[i] > closes[i - 1]:
            up += vols[i]
        elif closes[i] < closes[i - 1]:
            dn += vols[i]
    return up / dn if dn else None


def big_down_recent(closes, vols, days=5, drop=-0.05, mult=1.5):
    """Any day in the last `days` sessions down >=5% on volume >= 1.5x its 50-day average?"""
    avg = sum(vols[-50:]) / min(50, len(vols))
    for i in range(len(closes) - days, len(closes)):
        if closes[i] / closes[i - 1] - 1 <= drop and vols[i] >= mult * avg:
            return True
    return False


def distribution_days(closes, vols, n=25, drop=-0.002):
    c = 0
    for i in range(len(closes) - n, len(closes)):
        if closes[i] / closes[i - 1] - 1 <= drop and vols[i] > vols[i - 1]:
            c += 1
    return c


def index_gate(closes, vols, rules=RULES):
    """GO only if above both averages and distribution days <= limit. Anything unclear = NO-GO.
    This definition is mine; the earlier screen's exact gate code was not seen."""
    s50, s200 = sma(closes, 50), sma(closes, 200)
    if s200 is None:
        return dict(status="UNKNOWN (treated as NO-GO)", above50=None, above200=None, dist=None)
    dist = distribution_days(closes, vols, rules["dist_window"]) if sum(vols[-25:]) > 0 else None
    a50, a200 = closes[-1] > s50, closes[-1] > s200
    go = a50 and a200 and dist is not None and dist <= rules["dist_limit"]
    status = "GO" if go else "NO-GO"
    if dist is None:
        status = "UNKNOWN (no index volume; treated as NO-GO)"
    return dict(status=status, above50=a50, above200=a200, dist=dist)


def yoy(cur, prior):
    """Growth vs a year ago. None when the base is missing, zero or negative (no fake %)."""
    if cur is None or prior is None or prior <= 0:
        return None
    return cur / prior - 1


def cagr(last, first, years):
    if last is None or first is None or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def rs_ranks(rets):
    """0-100 percentile of 12-month return among the given stocks (IBD-style rating)."""
    order = sorted(rets, key=rets.get)
    n = len(order)
    return {s: (100.0 * i / (n - 1) if n > 1 else 50.0) for i, s in enumerate(order)}


def year_ago(series, qdates):
    """Value for the quarter ~1 year before the latest one, matched BY DATE.
    Yahoo sometimes skips a quarter, so 'the 5th column' is not always a year ago (VIJAYA case)."""
    if not series or not qdates:
        return None
    for v, d in zip(series, qdates):
        if abs((qdates[0] - d).days - 365) <= 20:
            return v
    return None


def statement_lagging(latest_q_end, last_reported, next_earnings=None):
    """True if the data we hold is a quarter behind: the company reported ~a quarter after our
    latest statement's quarter-end, or its NEXT result date is already two quarters out
    (the KARURVYSYA / COFORGE case)."""
    if latest_q_end is None:
        return None
    if last_reported is not None and last_reported >= latest_q_end + timedelta(days=92):
        return True
    if next_earnings is not None and next_earnings >= latest_q_end + timedelta(days=183):
        return True
    return False


def is_bank(sector, industry):
    return "bank" in (industry or "").lower()


def evaluate(px, fund, rs_rank, rs_gap, rules, today):
    """Score one stock. px: price stats dict. fund: fundamentals dict (see data_yf). Returns a row."""
    flags = []
    eps_q = fund.get("eps_q") or []
    rev_q = fund.get("rev_q") or []
    ni_q = fund.get("ni_q") or []
    qd = fund.get("qdates") or []
    eps_g = yoy(eps_q[0], year_ago(eps_q, qd)) if eps_q else None
    sales_g = yoy(rev_q[0], year_ago(rev_q, qd)) if rev_q else None
    ni_g = yoy(ni_q[0], year_ago(ni_q, qd)) if ni_q else None
    lagging = statement_lagging(qd[0] if qd else None, fund.get("last_reported"), fund.get("next_earnings"))
    if lagging and fund.get("vendor_rev_g") is not None and fund.get("vendor_ni_g") is not None:
        # statement is a quarter behind: Yahoo's own growth fields already show the newer quarter
        eps_g, sales_g, ni_g = fund["vendor_ni_g"], fund["vendor_rev_g"], fund["vendor_ni_g"]
        flags.append("C-FROM-VENDOR(statement a quarter behind)")
    ea = fund.get("eps_a") or []
    cg = cagr(ea[0], ea[3], 3) if len(ea) >= 4 else None
    roe = fund.get("roe")
    if roe is None and fund.get("roe_calc") is not None:
        roe = fund["roe_calc"]
        flags.append("ROE-CALC(Yahoo had none)")

    C = eps_g is not None and sales_g is not None and eps_g >= rules["eps_q_yoy"] and sales_g >= rules["sales_q_yoy"]
    A = cg is not None and roe is not None and cg >= rules["eps_3y_cagr"] and roe >= rules["roe"]
    N = px["pct_high"] >= 1 - rules["near_high"]
    S = px["updown"] is not None and px["updown"] >= rules["updown"]
    L = rs_gap >= rules["rs_gap"]
    inst = fund.get("inst")
    I = inst is not None and inst >= rules["inst"]

    if eps_g is None or sales_g is None:
        flags.append("NA-GROWTH(no year-ago quarter or base<=0)")
    if eps_g is not None and sales_g is not None and sales_g > 0 and eps_g > 2.5 * sales_g:
        flags.append("PROFIT>2.5xSALES")
    if eps_g is not None and eps_g > 1.0:
        flags.append("BASE-CHECK(>100%)")
    if px["big_down"]:
        flags.append("BIG-DOWN-DAY")
    if lagging:
        flags.append("STALE(newer result out)")
    ne = fund.get("next_earnings")
    if ne is not None and 0 <= (ne - today).days <= 14:
        flags.append("RESULTS<=14d")
    for name, mine, vend in (("SALES", sales_g, fund.get("vendor_rev_g")), ("PROFIT", ni_g, fund.get("vendor_ni_g"))):
        if mine is not None and vend is not None and abs(mine - vend) > 0.05:
            flags.append(f"CHECK-{name}(mine {mine:+.0%} vs vendor {vend:+.0%})")
    if is_bank(fund.get("sector"), fund.get("industry")):
        flags.append("BANK(check NPA by hand)")
    pe = fund.get("pe")
    if pe is not None and pe > 100:
        flags.append("PE>100")

    tests = dict(C=C, A=A, N=N, S=S, L=L, I=I)
    core = C and A
    bad = [f for f in flags if f.startswith(("STALE", "CHECK", "NA-"))]
    return dict(
        core=core, core_clean=core and not bad, tests=sum(tests.values()),
        **{k: ("Y" if v else "n") for k, v in tests.items()},
        eps_q_yoy=eps_g, sales_q_yoy=sales_g, eps_3y_cagr=cg, roe=roe, pe=pe, pb=fund.get("pb"),
        rs_rank=round(rs_rank), rs_gap_pts=round(rs_gap * 100, 1),
        latest_q=qd[0].isoformat() if qd else "", next_earnings=ne.isoformat() if ne else "",
        flags="; ".join(flags),
    )
