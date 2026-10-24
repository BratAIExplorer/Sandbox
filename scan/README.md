# CANSLIM-style scan (India + US). Read-only. Places no orders.

## Run on your PC (Windows, Python 3.8+)
1. `pip install yfinance pandas`
2. `python data_source_test.py` (must print OK for US and NSE first)
3. Trial: `python scan/run_scan.py india --limit 40`
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
