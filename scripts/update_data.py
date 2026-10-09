"""
Download daily closes for the 13 indices from Yahoo Finance and write data/indices.json.

- History: as far back as Yahoo has it, capped just under 30 years.
- Calendar: every weekday (Mon-Fri) from the first available date to the latest date.
- Gaps (holidays, missing days): filled with the previous date's close, so that day counts as 0%.
- If a download fails, that index keeps the data already in data/indices.json.
- Energy futures go to data/energy.json. UK gasoil comes from OilPriceAPI (needs the OILPRICEAPI_KEY secret).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# key, display name, Yahoo tickers to try in order (the first one that returns data is used)
INDICES = [
    ("AUS200", "Australia 200 (ASX 200)",          ["^AXJO"]),
    ("CAN60",  "Canada 60 (S&P/TSX 60)",           ["^TX60", "XIU.TO", "^GSPTSE"]),
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
SUBSTITUTE = {
    "XIU.TO": "Canada 60 uses the iShares S&P/TSX 60 ETF (XIU.TO); on its quarterly dividend days the daily % is slightly lower than the index",
    "^GSPTSE": "Canada 60 uses the S&P/TSX Composite because the TSX 60 was unavailable",
}
MIN_ROWS = 250  # a ticker must return at least about a year of history to be used
DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "indices.json"
ENERGY_OUT = DATA / "energy.json"

# Energy futures (Yahoo front-month continuous). Saved in USD per barrel: value x factor.
# key, display name, native unit, tickers to try, factor to USD/bbl
ENERGY = [
    ("BRENT", "Brent crude",          "USD/bbl", ["BZ=F"],          1.0),
    ("WTI",   "WTI crude (Texas)",    "USD/bbl", ["CL=F"],          1.0),
    ("HO",    "US heating oil",       "USD/gal", ["HO=F"],          42.0),
    ("RB",    "US gasoline (RBOB)",   "USD/gal", ["RB=F"],          42.0),
    ("GO",    "UK gasoil (ICE)",      "USD/t",   ["OilPriceAPI"],   1 / 7.45),
]
ENERGY_MIN_ROWS = 250

# UK gasoil is not on Yahoo Finance. It comes from OilPriceAPI (free plan: 50 requests/day).
# The API key is a GitHub secret (OILPRICEAPI_KEY). Each run adds the latest price; history builds up day by day.
OPA_BASE = "https://api.oilpriceapi.com/v1"
OPA_CODES = ["GASOIL_USD", "GASOIL_FUTURES"]  # tried in order
OPA_MAX_DAYS, OPA_MIN_DAYS = 1825, 10         # /ohlc window limits (API maximum is 1825 days)



def download(tickers, start, end, allow_negative=False, min_rows=None):
    """Return (ticker_used, Series of closes indexed by date) or (None, None)."""
    import yfinance as yf
    min_rows = MIN_ROWS if min_rows is None else min_rows
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
        close = clean(close, allow_negative)
        if len(close) < min_rows:
            print(f"  {t}: only {len(close)} rows, trying the next ticker")
            continue
        return t, close
    return None, None


def clean(close, allow_negative=False):
    close = pd.to_numeric(close, errors="coerce").dropna()
    if not allow_negative:          # index levels are always positive; oil futures once were not (WTI, Apr 2020)
        close = close[close > 0]
    idx = pd.to_datetime(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    return close[~close.index.duplicated(keep="last")].sort_index()


def load_existing(path):
    """Previous file's real values per series (forward-filled repeats removed)."""
    if not path.exists():
        return {}
    try:
        old = json.loads(path.read_text())
        dates = pd.to_datetime(old["dates"])
        res = {}
        for k, vals in old["series"].items():
            s = pd.Series(vals, index=dates, dtype="float64").dropna()
            s = s[s.ne(s.shift())]  # drop repeats created by forward fill
            res[k] = (s, old.get("meta", {}).get(k, {}))
        return res
    except Exception as e:
        print(f"Could not read existing data in {path.name}: {e}")
        return {}


def opa_get(path, params, key):
    """GET an OilPriceAPI endpoint. Returns parsed JSON or raises. Retries once on 503 (data briefly stale)."""
    import time
    from urllib.error import HTTPError
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    url = f"{OPA_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Token {key}", "Accept": "application/json",
                                "User-Agent": "finance-tools-daily-update"})
    for attempt in (1, 2):
        try:
            with urlopen(req, timeout=30) as r:
                return json.load(r)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code == 503 and attempt == 1:
                print(f"  OilPriceAPI {path}: 503, retrying in 60 s")
                time.sleep(60)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body}") from None


def opa_point(data):
    """(London trade date, price in USD/t) from a /prices/latest response, or None."""
    from zoneinfo import ZoneInfo
    d = data.get("data", data) if isinstance(data, dict) else {}
    if isinstance(d.get("prices"), list) and d["prices"]:
        d = d["prices"][0]
    price = d.get("price")
    when = d.get("as_of") or d.get("created_at")
    if price is None or not when:
        return None
    if d.get("synthetic"):
        print("  OilPriceAPI: value is carried forward (synthetic), not a new price; skipped")
        return None
    unit = str(d.get("unit") or "").lower()
    if unit and "ton" not in unit and unit not in ("t", "mt"):
        print(f"  OilPriceAPI: unexpected unit '{unit}'; skipped")
        return None
    ts = pd.Timestamp(when)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
    day = pd.Timestamp(ts.tz_convert(ZoneInfo("Europe/London")).date())
    return day, float(price)


DATE_KEYS = ("date", "trade_date", "trading_date", "day", "period", "timestamp", "time", "as_of")
PRICE_KEYS = ("settlement", "settle", "close", "last_price", "price")
MONTH_KEYS = ("contract_month", "contract", "month", "expiry_month")


def opa_daily(resp, today):
    """Daily closes from an /ohlc response (layout not documented). Finds every list of rows, tags each row
    with its contract month when one is given, and stitches a front-month series: on each date the nearest
    contract month that has a price wins. Logs the layout. Returns Series of raw USD/t, or None."""
    lists = []   # (path, contract month of parent or None, rows)

    def walk(o, path, month):
        if isinstance(o, dict):
            m = next((str(o[k]) for k in MONTH_KEYS if isinstance(o.get(k), (str, int))), month)
            for k, v in o.items():
                walk(v, f"{path}.{k}", m)
        elif isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and any(any(k in x for k in PRICE_KEYS) for x in o):
                lists.append((path, month, o))
            for i, v in enumerate(o[:500]):
                if isinstance(v, (dict, list)):
                    walk(v, f"{path}[{i}]", month)

    walk(resp, "resp", None)
    if isinstance(resp, dict):
        extra = {k: resp[k] for k in ("truncated", "days_requested", "days_served", "page", "total", "next", "count") if k in resp}
        print(f"  GO: ohlc layout: top keys {list(resp)[:12]} {extra or ''}; {len(lists)} row list(s)")
    rows = []
    for path, month, rs in lists:
        pts = []
        for r in rs:
            d = next((r[k] for k in DATE_KEYS if r.get(k)), None)
            v = next((r[k] for k in PRICE_KEYS if r.get(k) is not None), None)
            m = next((str(r[k]) for k in MONTH_KEYS if r.get(k)), month) or ""
            try:
                pts.append((pd.Timestamp(str(d)[:10]), m, float(v)))
            except Exception:
                continue
        if pts:
            ds = [q[0] for q in pts]
            print(f"    {path[:60]} month={month or '-'}: {len(pts)} rows {min(ds):%Y-%m-%d} to {max(ds):%Y-%m-%d}, "
                  f"first row keys {list(rs[0])[:10]}")
        rows += pts
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "month", "price"])
    df = df[df["price"] > 0]
    # front month: for each date the smallest contract month that has a price ("" = untagged, used as is)
    df = df.sort_values(["date", "month"]).drop_duplicates("date", keep="first")
    s = pd.Series(df["price"].values, index=pd.DatetimeIndex(df["date"]), dtype="float64").sort_index()
    if s.empty or (today - s.index.max()).days > 10:
        print(f"  GO: ohlc series ends {s.index.max():%Y-%m-%d}, too old; ignored")
        return None
    # keep only the continuous recent stretch (drop old fragments separated by a gap of over 3 weeks)
    gaps = s.index.to_series().diff().dt.days
    big = gaps[gaps > 21]
    if len(big):
        cut = big.index.max()
        print(f"  GO: dropped {int((s.index < cut).sum())} rows before a {int(big.loc[cut])}-day gap ending {cut:%Y-%m-%d}")
        s = s[s.index >= cut]
    return s


def gasoil_latest(last_saved=None):
    """Return (code used, Series of new raw USD/t points) or (None, None).
    last_saved: date of the last gasoil price already in energy.json (None on the first run)."""
    import os
    key = os.environ.get("OILPRICEAPI_KEY", "").strip()
    if not key:
        print("  GO: OILPRICEAPI_KEY is not set (add it under Settings > Secrets and variables > Actions)")
        return None, None
    got, used = [], "ice-gasoil"
    # 1) daily closes. /ohlc takes "days" back from today (max 1825). One request returns many days.
    def ohlc(days):
        try:
            resp = opa_get("/futures/ice-gasoil/ohlc", {"days": days}, key)
        except Exception as e:
            print(f"  GO: ohlc {days} days: not available: {e}")
            return None, ("HTTP 401" in str(e) or "HTTP 429" in str(e))   # bad key / quota: stop
        daily = opa_daily(resp, pd.Timestamp.now().normalize())
        if daily is None or not len(daily):
            print(f"  GO: ohlc {days} days: no daily closes in response: {json.dumps(resp)[:300]}")
            return None, False
        print(f"  GO: ohlc {days} days: OK, {daily.index.min():%Y-%m-%d} to {daily.index.max():%Y-%m-%d} ({len(daily)} rows)")
        return daily, False

    daily = None
    if last_saved is not None:
        # history already saved: only ask for the days since the last saved date, plus a buffer
        days = min(OPA_MAX_DAYS, max(10, (pd.Timestamp.now().normalize() - last_saved).days + 7))
        daily, _ = ohlc(days)
    else:
        # first run: find the longest history the plan allows (bisection between a pass and a fail)
        daily, stop = ohlc(OPA_MAX_DAYS)
        if daily is None and not stop:
            ok_days, ok_data = OPA_MIN_DAYS, None
            ok_data, stop = ohlc(ok_days)
            bad, tries = OPA_MAX_DAYS, 0
            while ok_data is not None and not stop and bad - ok_days > 5 and tries < 10:
                mid = (ok_days + bad) // 2
                d, stop = ohlc(mid)
                tries += 1
                if d is not None:
                    ok_days, ok_data = mid, d
                else:
                    bad = mid
            daily = ok_data
            if daily is not None:
                print(f"  GO: longest history allowed is about {ok_days} days")
    if daily is not None:
        got.append(daily)
    # 2) latest price
    for code in OPA_CODES:
        try:
            pt = opa_point(opa_get("/prices/latest", {"by_code": code}, key))
        except Exception as e:
            print(f"  GO: OilPriceAPI {code}: {e}")
            continue
        if pt:
            day, price = pt
            print(f"  GO: OilPriceAPI {code} = {price} USD/t for {day:%Y-%m-%d}")
            got.append(pd.Series([price], index=[day], dtype="float64"))
            used = code
            break
        print(f"  GO: OilPriceAPI {code}: no usable price in the response")
    if not got:
        return None, None
    s = pd.concat(got)   # latest price overrides the daily close of the same date
    return used, s[~s.index.duplicated(keep="last")].sort_index()


# When each market's day is final: (time zone, local hour after which today's bar is complete)
CLOSE_AT = {
    "AUS200": ("Australia/Sydney", 16.5), "JPN225": ("Asia/Tokyo", 15.75), "HK50": ("Asia/Hong_Kong", 16.5),
    "UK100": ("Europe/London", 17.0), "GER40": ("Europe/Berlin", 18.0), "FRA40": ("Europe/Paris", 18.0),
    "ITA40": ("Europe/Rome", 18.0), "ESP35": ("Europe/Madrid", 18.0),
    "US30": ("America/New_York", 16.5), "US100": ("America/New_York", 16.5), "US500": ("America/New_York", 16.5),
    "US2000": ("America/New_York", 16.5), "CAN60": ("America/Toronto", 16.5),
    # CME energy futures: trade date ends at 17:00 New York; the 18:00 restart belongs to the next trade date
    "BRENT": ("America/New_York", 17.0), "WTI": ("America/New_York", 17.0),
    "HO": ("America/New_York", 17.0), "RB": ("America/New_York", 17.0), "GO": ("Europe/London", 17.5),
}


def drop_unfinished(key, s, now):
    """Remove bars for trading days that have not closed yet (intraday values)."""
    if key not in CLOSE_AT or s.empty:
        return s
    from zoneinfo import ZoneInfo
    tz, hour = CLOSE_AT[key]
    local = now.astimezone(ZoneInfo(tz))
    last_done = pd.Timestamp(local.date())
    if local.hour + local.minute / 60 < hour:
        last_done -= pd.Timedelta(days=1)
    if key in ("BRENT", "WTI", "HO", "RB") and local.hour >= 18:
        last_done = pd.Timestamp(local.date())  # evening session is tomorrow's trade date
    cut = s[s.index > last_done]
    if len(cut):
        print(f"  {key}: dropped {len(cut)} unfinished bar(s) after {last_done:%Y-%m-%d}")
    return s[s.index <= last_done]


def build(closes):
    """closes: {key: Series}. Returns (weekday calendar, forward-filled DataFrame on it)."""
    first = min(s.index.min() for s in closes.values())
    last = max(s.index.max() for s in closes.values())
    cal = pd.bdate_range(first, last)  # Mon-Fri
    df = pd.DataFrame({k: s for k, s in closes.items()})
    df = df.reindex(df.index.union(cal)).sort_index().ffill()  # gaps take the previous close
    return cal, df.reindex(cal)


def run_set(label, items, out, start, end, now, allow_negative=False, min_rows=None, digits=2):
    """Download one set of series and write its JSON file. Returns the list of failed keys."""
    existing = load_existing(out)
    closes, meta, failed = {}, {}, []
    for item in items:
        key, name, tickers = item[0], item[1], item[-2] if len(item) == 5 else item[2]
        unit = item[2] if len(item) == 5 else ""
        factor = item[4] if len(item) == 5 else 1.0
        print(f"{key}: trying {', '.join(tickers)}")
        if key == "GO":   # OilPriceAPI: add today's price to the history already saved
            if key in existing and (pd.Timestamp(now.date()) - existing[key][0].index.max()).days > 30:
                print(f"  GO: saved history ends {existing[key][0].index.max():%Y-%m-%d}, too old; discarded")
                del existing[key]
            used, new = gasoil_latest(existing[key][0].index.max() if key in existing else None)
            if new is not None:
                new = drop_unfinished(key, new, now)
                old = existing[key][0] / factor if key in existing else pd.Series(dtype="float64")
                s = pd.concat([old, new])
                s = s[~s.index.duplicated(keep="last")].sort_index()
                if s.empty:
                    print("  GO: only today's unfinished price so far; it is saved by a run after the 17:30 London settlement")
                    used, s = None, None
                else:
                    used = f"OilPriceAPI {used}"
            else:
                s = None
        else:
            used, s = download(tickers, start, end, allow_negative, min_rows)
        if s is None:
            failed.append(key)
            if key in existing:
                print(f"  {key}: download failed, keeping previous data")
                closes[key], meta[key] = existing[key]
            else:
                print(f"  {key}: download failed and there is no previous data")
            continue
        s = drop_unfinished(key, s, now)
        closes[key] = s * factor
        meta[key] = {"name": name, "ticker": used, "substitute": SUBSTITUTE.get(used, ""),
                     "first": s.index.min().strftime("%Y-%m-%d"),
                     "last": s.index.max().strftime("%Y-%m-%d")}
        if unit:
            meta[key].update({"unit": unit, "factor": factor})
        print(f"  {key}: {used}, {len(s)} rows, {meta[key]['first']} to {meta[key]['last']}")

    if not closes:
        print(f"{label}: nothing downloaded and no previous data; file not written.")
        return failed
    cal, df = build(closes)
    order = [it[0] for it in items if it[0] in df.columns]
    data = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance daily closes (yfinance)" + ("; UK gasoil from OilPriceAPI" if "GO" in order else ""),
        "dates": [d.strftime("%Y-%m-%d") for d in cal],
        "series": {k: [None if pd.isna(v) else round(float(v), digits) for v in df[k]] for k in order},
        "meta": {k: meta[k] for k in order},
        "failed": failed,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"{label}: wrote {out.name}, {len(cal)} dates x {len(order)} series. Failed: {failed or 'none'}")
    return failed


SCHED_INDEX = "15 21 * * *"    # 05:15 SGT
SCHED_ENERGY_WINTER = "15 22 * * *"  # 06:15 SGT


def plan(schedule, ny_now):
    """Decide what this run downloads.
    Indices: the 05:15 SGT run (and manual runs). Energy: every run. GitHub often starts scheduled
    runs late (sometimes hours), so nothing depends on the exact start time: unfinished trading days
    are dropped by drop_unfinished(). In US winter the 05:15 run is before the 17:00 New York close,
    so the 06:15 run picks up that day's energy prices."""
    if not schedule:
        return True, True
    return schedule == SCHED_INDEX, True


def main():
    from zoneinfo import ZoneInfo
    import os
    now = datetime.now(timezone.utc)
    end = (now + timedelta(days=1)).date()
    start = (pd.Timestamp(now.date()) - pd.DateOffset(years=30) + pd.Timedelta(days=2)).date()
    schedule = os.environ.get("SCHEDULE", "").strip()
    ny = now.astimezone(ZoneInfo("America/New_York"))
    do_idx, do_energy = plan(schedule, ny)
    print(f"Run: {'schedule ' + schedule if schedule else 'manual/push'}; New York time {ny:%Y-%m-%d %H:%M %Z}. "
          f"Indices: {'yes' if do_idx else 'skip'}. Energy: {'yes' if do_energy else 'skip'}.")
    print()

    failed_idx = []
    if do_idx:
        failed_idx = run_set("Indices", INDICES, OUT, start, end, now)
        print()
    if do_energy:
        run_set("Energy", ENERGY, ENERGY_OUT, start, end, now, allow_negative=True,
                min_rows=ENERGY_MIN_ROWS, digits=3)

    if do_idx and len(failed_idx) == len(INDICES):
        print("No index downloaded.")
        sys.exit(1)


if __name__ == "__main__":
    main()
