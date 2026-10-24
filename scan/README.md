# CANSLIM-style scan: India, US, Malaysia, Japan, Euronext. Read-only. Places no orders.

## Run on your PC (Windows, Python 3.8+)
1. `pip install yfinance pandas`
2. `python data_source_test.py` (must print OK for US and NSE first)
3. Trial: `python scan/run_scan.py india --limit 40` (markets: india, us, malaysia, japan, euronext)
4. **Check 3 results by hand against the company's own filing before trusting anything.**
5. Full: `python scan/run_scan.py india --min-mcap 42000000000` and `python scan/run_scan.py us`
   (a full run is slow: prices are batched, fundamentals only fetched for stocks that pass the price filters; results are cached 24h in `.scan_cache/`).

Tests (no network): `python -m unittest scan/test_scan.py -v`

## What it does
Funnel: cleaned list -> has 1y prices -> liquid -> within 15% of 52w closing high -> up 12m -> scored.
Core (★) = C and A both pass. `clean` = core with no STALE / CHECK / NA flags.

## Added after the KARURVYSYA review
- STALE flag: company reported a newer quarter than the statement we hold.
- CHECK flag: my sales/profit growth vs Yahoo's own growth fields differ by >5 points (same vendor, so a weak check).
- NA instead of a % when last year's base is zero/negative; BASE-CHECK when EPS growth >100%.
- RS shown as points vs index AND a 0-100 rank. 52w high = closing high, with its date.
- Next results date; RESULTS<=14d flag. Up/down volume ratio and BIG-DOWN-DAY flag.
- Bank flag: NPA, margin, loan growth are NOT in Yahoo; check by hand.

## Known gaps (not done)
- Thresholds in `scan/logic.py` RULES were inferred from the earlier screen's output, not its code. Edit if wrong.
- Index gate definition is mine (GO = above 50 and 200-day and <=4 distribution days). Unknown = NO-GO.
- Institutional % (I) is weak/missing for many Indian stocks on Yahoo.
- No share-count (dilution) check. No true second data source.
- Yahoo is a free scrape and can be wrong or rate-limited. Nothing here is verified against filings.

## Markets, sizes, columns (added later)
- Universe files: `universe/*_all.csv`. India and US come from your exchange files; Malaysia (Bursa), Japan (Tokyo) and
  Euronext (Paris, Amsterdam, Brussels, Lisbon, Dublin, Milan, Oslo) come from Yahoo's screener via `universe/build_global.py`.
  Rows with no market cap (bonds, certificates, delisted) are dropped and listed in `dropped_*.csv`.
  Whether your IBKR account can trade each market (and Milan/Oslo) is NOT checked here.
- Gate/benchmark index per market: India ^CRSLDX, US ^GSPC, Malaysia ^KLSE, Japan ^N225 (Nikkei, not TOPIX), Euronext ^N100.
- Size buckets in US$ (FX from Yahoo): large >= $10B, mid $2-10B, small $300M-2B, penny = under $300M or price under $1.
  My cut-offs; edit `size_bucket` in `scan/logic.py`. `--bucket large mid` filters. Pennies get a PENNY flag (thin, high risk).
- Default liquidity floor US$500k/day (`--min-liq`). Lower it to see thinner names.
- Output columns include: Mkt cap, Price, P/E, Latest qtr, EPS qtr YoY, Sales qtr YoY, EPS 3y CAGR, ROE,
  Close vs 52w-high close, High date, RS gap, RS rank, Up/down vol, Shares YoY (plus US$ market cap and price, next results, flags).
- Yahoo's quarterly statements are sparse outside the US (Japan: 2 quarters, no revenue row). Where a year-ago quarter is
  missing, Yahoo's own growth field is used and flagged *-FROM-VENDOR (never counted as clean).
- Half-year reporters (common in Europe) can get a false STALE flag. A share split/bonus can fake a Shares YoY change.
