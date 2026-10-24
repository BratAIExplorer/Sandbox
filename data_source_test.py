"""Quick test: does Yahoo's free chart endpoint return prices for US, NSE and Bursa tickers?

Run: python data_source_test.py
Needs Python 3.8+. No installs. Read-only, places no orders.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

TICKERS = {
    "US": ["AAPL", "MSFT"],
    "NSE (India)": ["RELIANCE.NS", "TCS.NS"],
    "Bursa (Malaysia)": ["1155.KL", "1023.KL"],  # Maybank, CIMB
}


def fetch(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    res = data["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    stamps = res["timestamp"]
    return res["meta"].get("currency"), closes, stamps


def main():
    print(f"Run at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n")
    for market, symbols in TICKERS.items():
        for sym in symbols:
            try:
                cur, closes, stamps = fetch(sym)
                last_day = datetime.fromtimestamp(stamps[-1], timezone.utc).date()
                age = (datetime.now(timezone.utc).date() - last_day).days
                print(f"OK    {market:17} {sym:12} bars={len(closes):3} last_close={closes[-1]:.2f} {cur} "
                      f"last_bar={last_day} ({age}d old)")
            except Exception as e:
                print(f"FAIL  {market:17} {sym:12} {type(e).__name__}: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
