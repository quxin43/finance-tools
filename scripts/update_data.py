"""
Download daily closes for the 13 indices from Yahoo Finance and write data/indices.json.

- History: as far back as Yahoo has it, capped just under 30 years.
- Calendar: every weekday (Mon-Fri) from the first available date to the latest date.
- Gaps (holidays, missing days): filled with the previous date's close, so that day counts as 0%.
- If a download fails, that index keeps the data already in data/indices.json.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# key, display name, Yahoo tickers to try in order (the first one that returns data is used)
INDICES = [
    ("AUS200", "Australia 200 (ASX 200)",          ["^AXJO"]),
    ("CAN60",  "Canada 60 (S&P/TSX 60)",           ["^TX60", "TX60.TS", "^GSPTSE"]),
    ("FRA40",  "France 40 (CAC 40)",               ["^FCHI"]),
    ("GER40",  "Germany 40 (DAX)",                 ["^GDAXI"]),
    ("HK50",   "Hong Kong 50 (Hang Seng)",         ["^HSI"]),
    ("ITA40",  "Italy 40 (FTSE MIB)",              ["FTSEMIB.MI"]),
    ("JPN225", "Japan 225 (Nikkei 225)",           ["^N225"]),
    ("ESP35",  "Spain 35 (IBEX 35)",               ["^IBEX"]),
    ("UK100",  "UK 100 (FTSE 100)",                ["^FTSE"]),
    ("US30",   "US 30 (Dow Jones)",                ["^DJI"]),
    ("US100",  "US NDAQ 100 (Nasdaq-100)",         ["^NDX"]),
    ("US500",  "US SPX 500 (S&P 500)",             ["^GSPC"]),
    ("US2000", "US Small Cap 2000 (Russell 2000)", ["^RUT"]),
]
# tickers that are a stand-in for the intended index (shown as a note on the page)
SUBSTITUTE = {"^GSPTSE": "S&P/TSX Composite is used because the TSX 60 was unavailable"}
OUT = Path(__file__).resolve().parent.parent / "data" / "indices.json"


def download(tickers, start, end):
    """Return (ticker_used, Series of closes indexed by date) or (None, None)."""
    import yfinance as yf
    for t in tickers:
        try:
            df = yf.download(t, start=start, end=end, interval="1d",
                             auto_adjust=False, progress=False, threads=False)
        except Exception as e:
            print(f"  {t}: download error: {e}")
            continue
        if df is None or df.empty or "Close" not in df:
            print(f"  {t}: no data")
            continue
        close = df["Close"]
        if isinstance(close, pd.DataFrame):  # newer yfinance returns a one-column frame
            close = close.iloc[:, 0]
        close = clean(close)
        if close.empty:
            continue
        return t, close
    return None, None


def clean(close):
    close = pd.to_numeric(close, errors="coerce").dropna()
    close = close[close > 0]
    idx = pd.to_datetime(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    return close[~close.index.duplicated(keep="last")].sort_index()


def load_existing():
    """Previous file's real closes per index (forward-filled repeats removed)."""
    if not OUT.exists():
        return {}
    try:
        old = json.loads(OUT.read_text())
        dates = pd.to_datetime(old["dates"])
        res = {}
        for k, vals in old["series"].items():
            s = pd.Series(vals, index=dates, dtype="float64").dropna()
            s = s[s.ne(s.shift())]  # drop repeats created by forward fill
            res[k] = (s, old.get("meta", {}).get(k, {}))
        return res
    except Exception as e:
        print(f"Could not read existing data: {e}")
        return {}


def build(closes):
    """closes: {key: Series}. Returns (weekday calendar, forward-filled DataFrame on it)."""
    first = min(s.index.min() for s in closes.values())
    last = max(s.index.max() for s in closes.values())
    cal = pd.bdate_range(first, last)  # Mon-Fri
    df = pd.DataFrame({k: s for k, s in closes.items()})
    df = df.reindex(df.index.union(cal)).sort_index().ffill()  # gaps take the previous close
    return cal, df.reindex(cal)


def main():
    now = datetime.now(timezone.utc)
    end = (now + timedelta(days=1)).date()
    start = (pd.Timestamp(now.date()) - pd.DateOffset(years=30) + pd.Timedelta(days=2)).date()
    existing = load_existing()

    closes, meta, failed = {}, {}, []
    for key, name, tickers in INDICES:
        print(f"{key}: trying {', '.join(tickers)}")
        used, s = download(tickers, start, end)
        if s is None:
            failed.append(key)
            if key in existing:
                print(f"  {key}: download failed, keeping previous data")
                closes[key], meta[key] = existing[key]
            else:
                print(f"  {key}: download failed and there is no previous data")
            continue
        closes[key] = s
        meta[key] = {"name": name, "ticker": used, "substitute": SUBSTITUTE.get(used, ""),
                     "first": s.index.min().strftime("%Y-%m-%d"),
                     "last": s.index.max().strftime("%Y-%m-%d")}
        print(f"  {key}: {used}, {len(s)} rows, {meta[key]['first']} to {meta[key]['last']}")

    if len(failed) == len(INDICES):
        print("No index downloaded; leaving the data file unchanged.")
        sys.exit(1)

    cal, df = build(closes)
    order = [k for k, _, _ in INDICES if k in df.columns]
    data = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance daily closes (yfinance)",
        "dates": [d.strftime("%Y-%m-%d") for d in cal],
        "series": {k: [None if pd.isna(v) else round(float(v), 2) for v in df[k]] for k in order},
        "meta": {k: meta[k] for k in order},
        "failed": failed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Wrote {OUT}: {len(cal)} dates x {len(order)} indices. Failed: {failed or 'none'}")


if __name__ == "__main__":
    main()
