"""
Download daily closes for the 13 indices from Yahoo Finance and write data/indices.json.

- History: everything Yahoo has, merged with what is already saved, so history only grows.
- Calendar: every weekday (Mon-Fri) from the first available date to the latest date.
- Gaps (holidays, missing days): filled with the previous date's close, so that day counts as 0%.
- If a download fails, that index keeps the data already in data/indices.json.
- Energy futures go to data/energy.json. UK gasoil comes from OilPriceAPI (needs the OILPRICEAPI_KEY secret).
- Soybeans, corn, wheat, soybean meal and oil (CBOT) and heating oil go to data/agri.json; contract months to data/agri_curve.json.
- Gold, silver, platinum, palladium and copper go to data/metals.json; their contract months go to data/metal_curve.json.
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

# Precious metals (Yahoo COMEX front-month continuous), USD per troy ounce. Same layout as ENERGY.
METALS_OUT = DATA / "metals.json"
METALS = [
    ("GOLD",      "Gold (COMEX)",        "USD/oz", ["GC=F"], 1.0),
    ("SILVER",    "Silver (COMEX)",      "USD/oz", ["SI=F"], 1.0),
    ("PLATINUM",  "Platinum (NYMEX)",    "USD/oz", ["PL=F"], 1.0),
    ("PALLADIUM", "Palladium (NYMEX)",   "USD/oz", ["PA=F"], 1.0),
    ("COPPER",    "Copper (COMEX)",      "USD/lb", ["HG=F"], 1.0),
]

# Agriculture (Yahoo CBOT front-month continuous; Yahoo quotes grains in US cents per bushel, soybean meal in USD per
# short ton, soybean oil in US cents per pound). Heating oil is downloaded again here for the soy oil - heating oil pair.
AGRI_OUT = DATA / "agri.json"
AGRI = [
    ("SOY",    "Soybeans (CBOT)",      "¢/bu",    ["ZS=F"], 1.0),
    ("CORN",   "Corn (CBOT)",          "¢/bu",    ["ZC=F"], 1.0),
    ("WHEAT",  "Wheat (CBOT)",         "¢/bu",    ["ZW=F"], 1.0),
    ("MEAL",   "Soybean meal (CBOT)",  "USD/st",  ["ZM=F"], 1.0),
    ("SOYOIL", "Soybean oil (CBOT)",   "¢/lb",    ["ZL=F"], 1.0),
    ("HO",     "US heating oil",       "USD/gal", ["HO=F"], 1.0),
]
# Series computed from others: key -> (name, unit, [(source key, multiplier), ...]); value = sum of source x multiplier.
# One bushel of soybeans crushes into about 44 lb of meal (0.022 short ton; x100 for cents) and 11 lb of oil.
# One US gallon of soybean oil weighs about 7.5 lb (cents/lb x 7.5 / 100 = USD/gal).
AGRI_DERIVED = {
    "SOYPROD": ("Soy oil + meal (crush value)", "¢/bu", [("MEAL", 2.2), ("SOYOIL", 11.0)]),
    "BOGAL":   ("Soybean oil (per gallon)",     "USD/gal", [("SOYOIL", 0.075)]),
}

# UK gasoil is not on Yahoo Finance. It comes from OilPriceAPI (free plan: 50 requests/day).
# The API key is a GitHub secret (OILPRICEAPI_KEY). Each run adds the latest price; history builds up day by day.
OPA_BASE = "https://api.oilpriceapi.com/v1"
OPA_CODES = ["GASOIL_USD", "GASOIL_FUTURES"]  # tried in order
OPA_HIST = "settlement-nearest-v3"         # changes force one full re-download of the gasoil history
OPA_LAST = {}                                 # latest OilPriceAPI responses, reused for the futures curve
OPA_MAX_DAYS, OPA_MIN_DAYS = 1825, 10         # /ohlc window limits (API maximum is 1825 days)



def download(tickers, start, end, allow_negative=False, min_rows=None):
    """Return (ticker_used, Series of closes indexed by date) or (None, None)."""
    import yfinance as yf
    min_rows = MIN_ROWS if min_rows is None else min_rows
    for t in tickers:
        try:
            span = {"period": "max"} if start is None else {"start": start, "end": end}
            df = yf.download(t, interval="1d", auto_adjust=False, progress=False, threads=False, **span)
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
    for li, (path, month, rs) in enumerate(lists):
        pts = []
        for r in rs:
            d = next((r[k] for k in DATE_KEYS if r.get(k)), None)
            if "settlement" in r:          # official ICE settlement only; a row without one yet is skipped
                v = r["settlement"]
            else:
                v = next((r[k] for k in PRICE_KEYS if r.get(k) is not None), None)
            m = next((str(r[k]) for k in MONTH_KEYS if r.get(k)), month) or ""
            try:
                pts.append((pd.Timestamp(str(d)[:10]), m, float(v)))
            except Exception:
                continue
        if pts and (li < 2 or li == len(lists) - 1):   # log the first two and the last list only
            ds = [q[0] for q in pts]
            print(f"    {path[:60]} month={month or '-'}: {len(pts)} rows {min(ds):%Y-%m-%d} to {max(ds):%Y-%m-%d}, "
                  f"first row keys {list(rs[0])[:10]}")
        rows += pts
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "month", "price"])
    df = df[df["price"] > 0]
    # Contract choice per date: the nearest contract still trading that day (e.g. October until it expires
    # around the 12th, then November), the same contract CMC's "Low Sulphur Gasoil - Cash" follows.
    # A contract only has rows while it trades, so the earliest month with a settlement that day is the nearest.
    # Months before the date's own month are never used. Untagged rows are used as is.
    per = pd.PeriodIndex(df["month"].where(df["month"].str.match(r"^\d{4}-\d{2}"), None).str[:7], freq="M")
    target = pd.PeriodIndex(df["date"], freq="M")
    gap = [(m - t).n if m is not pd.NaT and m == m else 0 for m, t in zip(per, target)]
    df["rank"] = [g if g >= 0 else 1000 - g for g in gap]   # nearest from this month on; earlier months last
    df = df.sort_values(["date", "rank"]).drop_duplicates("date", keep="first")
    s = pd.Series(df["price"].values, index=pd.DatetimeIndex(df["date"]), dtype="float64").sort_index()
    if s.empty or (today - s.index.max()).days > 10:
        print(f"  GO: ohlc series ends {s.index.max():%Y-%m-%d}, too old; ignored")
        return None
    gaps = s.index.to_series().diff().dt.days
    for end, g in gaps[gaps > 14].items():
        print(f"  GO: no data for {int(g)} days before {end:%Y-%m-%d} (left empty on the chart)")
    return s


GO_MIN_USD_T = 200.0   # below this it is not a gasoil price in USD/t (OilPriceAPI's pre-2026 "gasoil" is
                       # NY Harbor heating oil in USD/gal, and holidays can carry junk values)


def clean_gasoil(s):
    """Remove impossible values and one-day spikes from a raw USD/t gasoil series."""
    bad = s[s < GO_MIN_USD_T]
    if len(bad):
        print(f"  GO: removed {len(bad)} values below {GO_MIN_USD_T:.0f} USD/t (wrong unit or junk), "
              f"{bad.index.min():%Y-%m-%d} to {bad.index.max():%Y-%m-%d}")
        s = s[s >= GO_MIN_USD_T]
    for _ in range(3):   # a day far from both neighbours while the neighbours agree is a bad print
        prev, nxt = s.shift(1), s.shift(-1)
        mid = (prev + nxt) / 2
        same_side = ((s - prev) * (s - nxt)) > 0
        spike = same_side & ((((s / mid - 1).abs() > 0.08) & ((nxt / prev - 1).abs() < 0.05))
                             | (((s / prev - 1).abs() > 0.15) & ((s / nxt - 1).abs() > 0.15)))
        if not spike.any():
            break
        for d in s[spike].index:
            print(f"  GO: removed spike {s[d]:.2f} on {d:%Y-%m-%d} (neighbours {prev[d]:.2f} / {nxt[d]:.2f})")
        s = s[~spike]
    return s


def gasoil_latest(last_saved=None):
    """Return (code used, Series of new raw USD/t points) or (None, None).
    last_saved: date of the last gasoil price already in energy.json (None on the first run)."""
    import os
    key = os.environ.get("OILPRICEAPI_KEY", "").strip()
    if not key:
        print("  GO: OILPRICEAPI_KEY is not set (add it under Settings > Secrets and variables > Actions)")
        return None, None
    got, used = [], "ice-gasoil settlements"
    # 1) daily closes. /ohlc takes "days" back from today (max 1825). One request returns many days.
    def ohlc(days):
        try:
            resp = opa_get("/futures/ice-gasoil/ohlc", {"days": days}, key)
        except Exception as e:
            print(f"  GO: ohlc {days} days: not available: {e}")
            return None, ("HTTP 401" in str(e) or "HTTP 429" in str(e))   # bad key / quota: stop
        OPA_LAST["resp"] = resp            # reused by the futures curve (every contract is in it)
        daily = opa_daily(resp, pd.Timestamp.now().normalize())
        if daily is None or not len(daily):
            print(f"  GO: ohlc {days} days: no daily closes in response: {json.dumps(resp)[:300]}")
            return None, False
        print(f"  GO: ohlc {days} days: OK, {daily.index.min():%Y-%m-%d} to {daily.index.max():%Y-%m-%d} ({len(daily)} rows)")
        return daily, False

    daily = None
    if last_saved is not None:
        # history already saved: only ask for the days since the last saved date, plus a buffer
        days = min(OPA_MAX_DAYS, max(10, (pd.Timestamp.now().normalize() - last_saved).days + 7))  # covers any outage
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
    # 2) fallback: the current contract list carries each contract's last settlement and its date
    if not got:
        try:
            resp = opa_get("/futures/ice-gasoil", {}, key)
            OPA_LAST["list"] = resp
            rows = [{"trading_date": c.get("settlement_date"), "settlement": c.get("settlement"),
                     "contract_month": c.get("contract_month")} for c in resp.get("contracts", [])]
            daily = opa_daily({"contracts": [{"contract_month": r["contract_month"], "daily_data": [r]} for r in rows]},
                              pd.Timestamp.now().normalize())
            if daily is not None and len(daily):
                print(f"  GO: contract list settlement {daily.iloc[-1]} USD/t for {daily.index[-1]:%Y-%m-%d}")
                got.append(daily)
                used = "ice-gasoil settlements"
        except Exception as e:
            print(f"  GO: contract list not available: {e}")
    if not got:
        return None, None
    s = pd.concat(got)
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
    # COMEX metals: same CME Globex hours as NYMEX energy
    "GOLD": ("America/New_York", 17.0), "SILVER": ("America/New_York", 17.0),
    "PLATINUM": ("America/New_York", 17.0), "PALLADIUM": ("America/New_York", 17.0), "COPPER": ("America/New_York", 17.0),
    # CBOT grains: day session ends 13:20 Chicago; the evening session (19:00) belongs to the next trade date
    "SOY": ("America/Chicago", 13.25), "CORN": ("America/Chicago", 13.25), "WHEAT": ("America/Chicago", 13.25),
    "MEAL": ("America/Chicago", 13.25), "SOYOIL": ("America/Chicago", 13.25),
}
CBOT_KEYS = ("SOY", "CORN", "WHEAT", "MEAL", "SOYOIL")
CME_KEYS = ("BRENT", "WTI", "HO", "RB", "GOLD", "SILVER", "PLATINUM", "PALLADIUM", "COPPER")   # Sunday 18:00 to Friday 17:00 New York, daily break 17-18


LIVE_LAST_BAR = True   # keep Yahoo's latest bar even if it is still trading (a live price); earlier days are
                       # replaced by final closes on later runs, because every run re-downloads the full history


def is_live(key, last_day, now):
    """True if the series' latest bar is still a live price at the time of this run (its market is trading)."""
    if key not in CLOSE_AT or key == "GO":
        return False
    from zoneinfo import ZoneInfo
    tz, close_h = CLOSE_AT[key]
    local = now.astimezone(ZoneInfo(tz))
    h, wd, d = local.hour + local.minute / 60, local.weekday(), pd.Timestamp(last_day).date()
    if key in CME_KEYS:
        # NYMEX/COMEX trade Sunday 18:00 to Friday 17:00 New York with a daily 17:00-18:00 break; while it is open,
        # Yahoo keeps updating the latest bar (also with the evening session) until it opens the next day's bar
        weekend = (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 18)
        in_break = 17 <= h < 18
        return not weekend and not in_break and (local.date() - d).days <= 1
    if key in CBOT_KEYS:
        # CBOT grains: Sunday-Friday 19:00-07:45 and Monday-Friday 08:30-13:20 Chicago time
        weekend = (wd == 4 and h >= 13.34) or wd == 5 or (wd == 6 and h < 19)
        open_now = h >= 19 or h < 7.75 or 8.5 <= h < 13.34
        return not weekend and open_now and (local.date() - d).days <= 1
    return local.date() == d and wd < 5 and h < close_h   # an index is live on its own trading day before the close


def drop_unfinished(key, s, now):
    """Remove bars for trading days that have not closed yet (intraday values).
    With LIVE_LAST_BAR, Yahoo series keep their latest (possibly live) bar; UK gasoil still waits for ICE's
    official settlement, because OilPriceAPI repeats yesterday's settlement as a placeholder until then."""
    if key not in CLOSE_AT or s.empty:
        return s
    if LIVE_LAST_BAR and key != "GO":
        return s
    from zoneinfo import ZoneInfo
    if key == "GO":   # ICE settlement for day D is published about 03:30 UTC on D+1
        last_done = pd.Timestamp((now.astimezone(timezone.utc) - timedelta(hours=28)).date())
        cut = s[s.index > last_done]
        if len(cut):
            print(f"  {key}: held back {len(cut)} day(s) after {last_done:%Y-%m-%d} until the official settlement is out")
        return s[s.index <= last_done]
    tz, hour = CLOSE_AT[key]
    local = now.astimezone(ZoneInfo(tz))
    last_done = pd.Timestamp(local.date())
    if local.hour + local.minute / 60 < hour:
        last_done -= pd.Timedelta(days=1)
    cut = s[s.index > last_done]
    if len(cut):
        print(f"  {key}: dropped {len(cut)} unfinished bar(s) after {last_done:%Y-%m-%d}")
    kept = s[s.index <= last_done]
    if key in CME_KEYS and len(kept) and not (s.index > kept.index[-1]).any():
        # Yahoo keeps updating the latest daily bar with evening-session trades (from 18:00 New York) until it
        # opens the next day's bar. So the latest bar is only trusted before 18:00 on its own date (the 17:00-18:00
        # break gives the closing price), or while the market is shut for the weekend; otherwise it is held back
        # and the next run, once Yahoo has a newer bar, saves the corrected value.
        d = kept.index[-1]
        evening = local.replace(tzinfo=None) >= (d + pd.Timedelta(hours=18)).to_pydatetime()
        wd, h = local.weekday(), local.hour + local.minute / 60
        weekend = (wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 18)
        if evening and not weekend:
            print(f"  {key}: held back {d:%Y-%m-%d}: Yahoo is still updating it with the evening session")
            kept = kept.iloc[:-1]
    return kept


FILL_LIMIT = {"GO": 5}   # weekdays a price may be carried forward; longer holes in the source stay empty


def build(closes):
    """closes: {key: Series}. Returns (weekday calendar, forward-filled DataFrame on it)."""
    first = min(s.index.min() for s in closes.values())
    last = max(s.index.max() for s in closes.values())
    cal = pd.bdate_range(first, last)  # Mon-Fri
    cols = {}
    for k, s in closes.items():
        lim = FILL_LIMIT.get(k)
        x = s.reindex(s.index.union(cal)).sort_index()
        if lim is None:
            x = x.ffill()                     # gaps take the previous close
        else:
            x = x.reindex(cal).ffill(limit=lim)
            x[x.index > s.index.max()] = s.iloc[-1]   # the latest price still carries forward to the end
        cols[k] = x.reindex(cal)
    return cal, pd.DataFrame(cols)


def run_set(label, items, out, start, end, now, allow_negative=False, min_rows=None, digits=2, derived=None):
    """Download one set of series and write its JSON file. Returns the list of failed keys."""
    existing = load_existing(out)
    closes, meta, failed = {}, {}, []
    for item in items:
        key, name, tickers = item[0], item[1], item[-2] if len(item) == 5 else item[2]
        unit = item[2] if len(item) == 5 else ""
        factor = item[4] if len(item) == 5 else 1.0
        print(f"{key}: trying {', '.join(tickers)}")
        if key == "GO":   # OilPriceAPI: add today's price to the history already saved
            if key in existing and existing[key][1].get("hist") != OPA_HIST:
                print("  GO: saved history was built by an older version of this script; downloading it again in full")
                del existing[key]
            used, new = gasoil_latest(existing[key][0].index.max() if key in existing else None)
            if new is not None:
                new = drop_unfinished(key, new, now)
                old = existing[key][0] / factor if key in existing else pd.Series(dtype="float64")
                s = pd.concat([old, new])
                s = clean_gasoil(s[~s.index.duplicated(keep="last")].sort_index())
                if s.empty:
                    print("  GO: no final settlement yet; saved by a later run (after about 04:00 UTC / 12:00 SGT)")
                    used, s = None, None
                else:
                    used = f"OilPriceAPI {used}"
            else:
                s = None
        else:
            used, s = download(tickers, start, end, allow_negative, min_rows)
            if s is not None and key in existing:
                old_s, old_m = existing[key]
                if old_m.get("ticker") == used:   # same source: keep saved days, new values win on overlap
                    s = drop_unfinished(key, s, now)
                    merged = pd.concat([old_s / factor, s])
                    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                    kept = int((merged.index < s.index.min()).sum())
                    if kept:
                        print(f"  {key}: kept {kept} saved days before Yahoo's first date {s.index.min():%Y-%m-%d}")
                    s = merged
                else:
                    print(f"  {key}: ticker changed ({old_m.get('ticker')} -> {used}); saved history not merged")
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
        if key == "GO":
            meta[key]["hist"] = OPA_HIST
        meta[key]["live"] = is_live(key, s.index.max(), now)
        print(f"  {key}: {used}, {len(s)} rows, {meta[key]['first']} to {meta[key]['last']}"
              + ("  (latest is a live price)" if meta[key]["live"] else ""))

    if not closes:
        print(f"{label}: nothing downloaded and no previous data; file not written.")
        return failed
    cal, df = build(closes)
    order = [it[0] for it in items if it[0] in df.columns]
    for k, (name, unit, parts) in (derived or {}).items():   # computed series, e.g. soybean crush value
        if not all(src in df.columns for src, _ in parts):
            print(f"  {k}: not computed (missing {', '.join(src for src, _ in parts if src not in df.columns)})")
            continue
        df[k] = sum(df[src] * mult for src, mult in parts)
        have = df[k].dropna()
        meta[k] = {"name": name, "ticker": " + ".join(f"{meta[src]['ticker']} x {mult:g}" for src, mult in parts),
                   "substitute": "", "unit": unit, "factor": 1.0, "derived": True,
                   "first": have.index.min().strftime("%Y-%m-%d"), "last": have.index.max().strftime("%Y-%m-%d"),
                   "live": any(meta[src].get("live") for src, _ in parts)}
        order.append(k)
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


# ---------------------------------------------------------------- futures curve (next 12 contract months)
CURVE_OUT = DATA / "curve.json"
CURVE_MONTHS = 12
MONTH_CODE = "FGHJKMNQUVXZ"   # Jan..Dec
CURVE_PAIRS = [("BRENT", "WTI"), ("HO", "RB"), ("HO", "GO")]
# Yahoo root, factor to USD/bbl, expiry rule
CURVE_LEGS = {
    "BRENT": ("BZ", 1.0, "brent"), "WTI": ("CL", 1.0, "wti"),
    "HO": ("HO", 42.0, "prev_month_end"), "RB": ("RB", 42.0, "prev_month_end"),
    "GO": (None, 1 / 7.45, "ice_gasoil"),
}


def _bday_back(d, n):
    """Step back n weekdays from date d (exchange holidays ignored)."""
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _last_bday(y, m):
    d = (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def contract_expiry(rule, y, m):
    """Approximate last trading day for delivery month (y, m); exchange holidays are ignored."""
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    if rule == "prev_month_end":            # NYMEX HO and RB: last business day of the month before
        return _last_bday(py, pm)
    if rule == "brent":                     # NYMEX BZ: last business day of the second month before
        qy, qm = (py, pm - 1) if pm > 1 else (py - 1, 12)
        return _last_bday(qy, qm)
    if rule == "wti":                       # NYMEX CL: 3 business days before the 25th of the month before
        d = datetime(py, pm, 25).date()
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return _bday_back(d, 3)
    if rule == "ice_gasoil":                # ICE gasoil: 2 business days before the 14th of the delivery month
        return _bday_back(datetime(y, m, 14).date(), 2)
    raise ValueError(rule)


def yahoo_last_settle(ticker, key, now):
    """(price, date, volume, open interest) of the latest finished daily bar for one Yahoo contract ticker.
    Missing values are None. Open interest comes from the ticker's quote details (one extra request)."""
    import yfinance as yf
    try:
        df = yf.download(ticker, period="1mo", interval="1d", auto_adjust=False, progress=False, threads=False)
    except Exception as e:
        print(f"    {ticker}: error {e}")
        return None, None, None, None
    if df is None or df.empty or "Close" not in df:
        return None, None, None, None
    def col(name):
        c = df[name] if name in df else None
        return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
    close = drop_unfinished(key, clean(col("Close"), allow_negative=True), now)
    if close.empty:
        return None, None, None, None
    day = close.index[-1]
    vol = None
    v = col("Volume")
    if v is not None:
        vi = pd.to_datetime(v.index)
        v.index = (vi.tz_localize(None) if vi.tz is not None else vi).normalize()
        if day in v.index and pd.notna(v.loc[day]):
            vol = int(v.loc[day])
    oi = None
    try:
        info = yf.Ticker(ticker).info or {}
        x = info.get("openInterest")
        oi = int(x) if x not in (None, "") else None
    except Exception:
        pass
    return float(close.iloc[-1]), day.strftime("%Y-%m-%d"), vol, oi


def gasoil_contract_settles(now):
    """{'YYYY-MM': (USD/t, date)} latest final ICE gasoil settlement per contract, from this run's OilPriceAPI data."""
    out = {}
    last_done = pd.Timestamp((now.astimezone(timezone.utc) - timedelta(hours=28)).date())   # same rule as GO
    resp = OPA_LAST.get("resp")
    for c in (resp or {}).get("contracts", []) if isinstance(resp, dict) else []:
        m = str(c.get("contract_month") or "")[:7]
        for r in c.get("daily_data", []) or []:
            d, v = r.get("trading_date"), r.get("settlement")
            if not d or v in (None, ""):
                continue
            t = pd.Timestamp(str(d)[:10])
            if t > last_done:
                continue
            if m not in out or t >= pd.Timestamp(out[m][1]):
                vol, oi = r.get("volume"), r.get("open_interest")
                out[m] = (float(v), t.strftime("%Y-%m-%d"),
                          int(vol) if vol not in (None, "") else None, int(oi) if oi not in (None, "") else None)
    if not out and isinstance(OPA_LAST.get("list"), dict):     # fallback: contract list
        for c in OPA_LAST["list"].get("contracts", []):
            m, d, v = str(c.get("contract_month") or "")[:7], c.get("settlement_date"), c.get("settlement")
            if m and d and v not in (None, "") and pd.Timestamp(str(d)[:10]) <= last_done:
                vol, oi = c.get("volume"), c.get("open_interest")
                out[m] = (float(v), str(d)[:10], int(vol) if vol not in (None, "") else None,
                          int(oi) if oi not in (None, "") else None)
    return out


def build_curve(now):
    """Next CURVE_MONTHS delivery months traded by both legs of each pair; prices in USD/bbl."""
    from zoneinfo import ZoneInfo
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    months = []
    y, m = today.year, today.month
    for _ in range(CURVE_MONTHS + 6):
        months.append((y, m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    cache, go = {}, None

    def leg(key, y, m):
        nonlocal go
        root, factor, rule = CURVE_LEGS[key]
        exp = contract_expiry(rule, y, m)
        if exp < today:
            return None                                   # expired: the next month takes its place
        if key == "GO":
            if go is None:
                go = gasoil_contract_settles(now)
            v = go.get(f"{y:04d}-{m:02d}")
            info = {"ticker": f"ICE gasoil {MONTH_CODE[m-1]}{y % 100:02d}", "native": v[0] if v else None,
                    "unit": "USD/t", "date": v[1] if v else None, "vol": v[2] if v else None, "oi": v[3] if v else None}
        else:
            t = f"{root}{MONTH_CODE[m-1]}{y % 100:02d}.NYM"
            if t not in cache:
                cache[t] = yahoo_last_settle(t, key, now)
            price, date, vol, oi = cache[t]
            info = {"ticker": t, "native": price, "unit": "USD/bbl" if factor == 1.0 else "USD/gal", "date": date,
                    "vol": vol, "oi": oi}
        info["expiry"] = exp.strftime("%Y-%m-%d")
        info["bbl"] = None if info["native"] is None else round(info["native"] * factor, 3)
        return info

    pairs = []
    for a, b in CURVE_PAIRS:
        rows = []
        for (y, m) in months:
            la = leg(a, y, m)
            lb = leg(b, y, m)
            if la is None or lb is None:
                continue
            rows.append({"month": f"{y:04d}-{m:02d}", "a": la, "b": lb})
            if len(rows) == CURVE_MONTHS:
                break
        ok = sum(1 for r in rows if r["a"]["bbl"] is not None and r["b"]["bbl"] is not None)
        print(f"  Curve {a}-{b}: {len(rows)} months ({rows[0]['month'] if rows else '-'} to {rows[-1]['month'] if rows else '-'}), "
              f"{ok} with both prices")
        for r in rows:
            for side in ("a", "b"):
                if r[side]["native"] is None:
                    print(f"    no price for {r[side]['ticker']}")
        pairs.append({"a": a, "b": b, "rows": rows})
    data = {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "Yahoo Finance monthly NYMEX contracts (BZ, CL, HO, RB); ICE gasoil from OilPriceAPI",
            "pairs": pairs}
    CURVE_OUT.parent.mkdir(parents=True, exist_ok=True)
    CURVE_OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Curve: wrote {CURVE_OUT.name}")


# ---------------------------------------------------------------- metal futures curve (gold and silver, COMEX)
METAL_CURVE_OUT = DATA / "metal_curve.json"
# Yahoo root, exchange suffix of the monthly contracts, unit, expiry rule
METAL_CURVE_LEGS = {"GOLD": ("GC", "CMX", "USD/oz", "metal"), "SILVER": ("SI", "CMX", "USD/oz", "metal"),
                    "PLATINUM": ("PL", "NYM", "USD/oz", "metal"), "PALLADIUM": ("PA", "NYM", "USD/oz", "metal"),
                    "COPPER": ("HG", "CMX", "USD/lb", "metal")}
METAL_CURVE_PAIRS = [("GOLD", "SILVER"), ("GOLD", "PLATINUM"), ("PLATINUM", "PALLADIUM"), ("COPPER", "GOLD")]

AGRI_CURVE_OUT = DATA / "agri_curve.json"
AGRI_CURVE_LEGS = {"SOY": ("ZS", "CBT", "¢/bu", "cbot"), "CORN": ("ZC", "CBT", "¢/bu", "cbot"),
                   "WHEAT": ("ZW", "CBT", "¢/bu", "cbot"), "MEAL": ("ZM", "CBT", "USD/st", "cbot"),
                   "SOYOIL": ("ZL", "CBT", "¢/lb", "cbot"), "HO": ("HO", "NYM", "USD/gal", "prev_month_end")}
AGRI_CURVE_PAIRS = [("SOY", "CORN"), ("WHEAT", "CORN"), ("SOYPROD", "SOY"), ("BOGAL", "HO")]


def comex_metal_expiry(y, m):
    """COMEX gold, silver, copper and NYMEX platinum, palladium: last trading day is the third-last business day
    of the delivery month (exchange holidays ignored)."""
    return _bday_back(_last_bday(y, m) + timedelta(days=1), 3)


def leg_expiry(rule, y, m):
    if rule == "metal":
        return comex_metal_expiry(y, m)
    if rule == "cbot":                       # CBOT grains and soy products: business day before the 15th
        return _bday_back(datetime(y, m, 15).date(), 1)
    return contract_expiry(rule, y, m)


def build_curve_set(now, label, out, legs, pairs, source, derived=None):
    """Contracts for the next 12 delivery months of each pair (Yahoo monthly tickers, e.g. GCZ26.CMX, ZSX26.CBT).
    Products list different months (gold Feb/Apr/Jun/Aug/Oct/Dec, silver Jan/Mar/May/Jul/Sep/Dec, soybeans
    Jan/Mar/May/Jul/Aug/Sep/Nov, corn and wheat Mar/May/Jul/Sep/Dec, ...), so a month is kept if either leg has a
    price; the page fills the other leg's price for that month by interpolating between its neighbouring contracts.
    derived: key -> (name, unit, [(leg key, multiplier), ...]); a derived leg has a price only when all its parts do."""
    from zoneinfo import ZoneInfo
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    months, y, m = [], today.year, today.month
    for _ in range(CURVE_MONTHS + 4):
        months.append((y, m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    cache = {}

    def base(key, y, m):
        root, exch, unit, rule = legs[key]
        t = f"{root}{MONTH_CODE[m-1]}{y % 100:02d}.{exch}"
        exp = leg_expiry(rule, y, m)
        if t not in cache:
            cache[t] = (None, None, None, None) if exp < today else yahoo_last_settle(t, key, now)
        price, date, vol, oi = cache[t]
        return {"ticker": t, "px": None if price is None else round(price, 4), "unit": unit,
                "date": date, "vol": vol, "oi": oi, "expiry": exp.strftime("%Y-%m-%d")}

    def leg(key, y, m):
        if key not in (derived or {}):
            return base(key, y, m)
        name, unit, parts = derived[key]
        ps = [(base(src, y, m), mult) for src, mult in parts]
        ok = all(l["px"] is not None for l, _ in ps)
        return {"ticker": " + ".join(l["ticker"] for l, _ in ps), "unit": unit,
                "px": round(sum(l["px"] * mult for l, mult in ps), 4) if ok else None,
                "date": min(l["date"] for l, _ in ps) if ok else None, "vol": None, "oi": None,
                "expiry": ps[0][0]["expiry"]}

    out_pairs = []
    for a, b in pairs:
        rows = []
        for (y, m) in months:
            la, lb = leg(a, y, m), leg(b, y, m)
            if la["px"] is None and lb["px"] is None:
                continue
            rows.append({"month": f"{y:04d}-{m:02d}", "a": la, "b": lb})
            if len(rows) == CURVE_MONTHS:
                break
        both = sum(1 for r in rows if r["a"]["px"] is not None and r["b"]["px"] is not None)
        print(f"  {label} curve {a}-{b}: {len(rows)} months ({rows[0]['month'] if rows else '-'} to "
              f"{rows[-1]['month'] if rows else '-'}), {both} with both prices")
        out_pairs.append({"a": a, "b": b, "rows": rows})
    if not any(p["rows"] for p in out_pairs):
        raise RuntimeError("no contract prices")
    data = {"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source, "pairs": out_pairs}
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"{label} curve: wrote {out.name}")


def build_metal_curve(now):
    build_curve_set(now, "Metal", METAL_CURVE_OUT, METAL_CURVE_LEGS, METAL_CURVE_PAIRS,
                    "Yahoo Finance monthly contracts (COMEX GC gold, SI silver, HG copper; NYMEX PL platinum, PA palladium)")


def build_agri_curve(now):
    build_curve_set(now, "Agri", AGRI_CURVE_OUT, AGRI_CURVE_LEGS, AGRI_CURVE_PAIRS,
                    "Yahoo Finance monthly contracts (CBOT ZS soybeans, ZC corn, ZW wheat, ZM soybean meal, "
                    "ZL soybean oil; NYMEX HO heating oil)", derived=AGRI_DERIVED)


SCHED_INDEX = "15 21 * * *"    # 05:15 SGT
SCHED_ENERGY_WINTER = "15 22 * * *"  # 06:15 SGT
SCHED_OVERLAP_SUMMER = "45 13 * * *"  # 21:45 SGT: US and European markets both open (US summer time)
SCHED_OVERLAP_WINTER = "45 14 * * *"  # 22:45 SGT: US and European markets both open (US winter time)
SCHED_ENERGY_NOON = "15 6 * * *"      # 14:15 SGT: previous day's final Yahoo settlements and ICE gasoil settlement


def plan(schedule, ny_now):
    """Decide what this run downloads: indices and energy on every run (scheduled or manual).
    The latest day may be a live price; each run re-downloads the full history, so earlier days end up
    with final closes whatever time GitHub actually starts the run.
    The US/Europe overlap run has two schedules (21:45 and 22:45 SGT); only the one matching US daylight
    saving time runs: 21:45 SGT in US summer time, 22:45 SGT in US winter time."""
    us_summer = bool(ny_now.dst())
    if schedule == SCHED_OVERLAP_SUMMER and not us_summer:
        return False, False
    if schedule == SCHED_OVERLAP_WINTER and us_summer:
        return False, False
    return True, True


def main():
    from zoneinfo import ZoneInfo
    import os
    now = datetime.now(timezone.utc)
    end = (now + timedelta(days=1)).date()
    start = None   # no cap: download everything Yahoo has
    schedule = os.environ.get("SCHEDULE", "").strip()
    ny = now.astimezone(ZoneInfo("America/New_York"))
    do_idx, do_energy = plan(schedule, ny)
    if not (do_idx or do_energy):
        print(f"Run: schedule {schedule}; New York time {ny:%Y-%m-%d %H:%M %Z}. Skipped: the other "
              f"US/Europe overlap run applies in {'summer' if ny.dst() else 'winter'} time.")
        return
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
        print()
        try:
            build_curve(now)
        except Exception as e:                      # the curve table is optional; never fail the run
            print(f"Curve: failed ({e}); previous curve.json kept")
        print()
        run_set("Metals", METALS, METALS_OUT, start, end, now, min_rows=ENERGY_MIN_ROWS, digits=3)
        print()
        try:
            build_metal_curve(now)
        except Exception as e:
            print(f"Metal curve: failed ({e}); previous metal_curve.json kept")
        print()
        run_set("Agri", AGRI, AGRI_OUT, start, end, now, min_rows=ENERGY_MIN_ROWS, digits=4, derived=AGRI_DERIVED)
        print()
        try:
            build_agri_curve(now)
        except Exception as e:
            print(f"Agri curve: failed ({e}); previous agri_curve.json kept")

    if do_idx and len(failed_idx) == len(INDICES):
        print("No index downloaded.")
        sys.exit(1)


if __name__ == "__main__":
    main()
