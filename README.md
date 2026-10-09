# Finance tools with daily index data

Four tabs: **Dip ladder**, **Rally ladder**, **Index gap** and **Energy gap**. A GitHub workflow downloads daily closes for 13 indices from Yahoo Finance every day at **05:15 Singapore time** (energy futures at 05:15 or 06:15 depending on US daylight saving) and republishes the site, so the Index gap tab is always current.

## Index pool

| Key | Index | Yahoo ticker |
|---|---|---|
| AUS200 | Australia 200 (ASX 200) | ^AXJO |
| CAN60 | Canada 60 (S&P/TSX 60) | ^TX60 (falls back to TX60.TS, then ^GSPTSE) |
| FRA40 | France 40 (CAC 40) | ^FCHI |
| GER40 | Germany 40 (DAX) | ^GDAXI |
| HK50 | Hong Kong 50 (Hang Seng) | ^HSI |
| ITA40 | Italy 40 (FTSE MIB) | FTSEMIB.MI |
| JPN225 | Japan 225 (Nikkei 225) | ^N225 |
| ESP35 | Spain 35 (IBEX 35) | ^IBEX |
| UK100 | UK 100 (FTSE 100) | ^FTSE |
| US30 | US 30 (Dow Jones) | ^DJI |
| US100 | US NDAQ 100 (Nasdaq-100) | ^NDX |
| US500 | US SPX 500 (S&P 500) | ^GSPC |
| US2000 | US Small Cap 2000 (Russell 2000) | ^RUT |

## Energy futures (Energy gap tab)

| Key | Market | Yahoo ticker | Native unit | Saved as USD/bbl |
|---|---|---|---|---|
| BRENT | Brent crude | BZ=F | USD/bbl | as is |
| WTI | WTI crude (Texas) | CL=F | USD/bbl | as is |
| HO | US heating oil | HO=F | USD/gal | × 42 |
| RB | US gasoline (RBOB) | RB=F | USD/gal | × 42 |
| GO | UK gasoil (ICE Low Sulphur Gasoil) | OilPriceAPI `GASOIL_USD` (not on Yahoo) | USD/t | ÷ 7.45 |

Saved in `data/energy.json`. UK gasoil comes from [OilPriceAPI](https://www.oilpriceapi.com) on the free plan (50 requests a day; each run uses 1 or 2), using ICE's official daily settlements from 24 March 2026, and the history grows from there. (OilPriceAPI's older "gasoil" data turned out to be US heating oil in USD/gal, so the script rejects any value below 200 USD/t. It also removes one-day spikes: a day more than 8% away from both neighbours while they agree, or more than 15% away from both.) The contract used on each date is the nearest one still trading (for example October until it expires around 12 October, then November), the same contract CMC's "Low Sulphur Gasoil - Cash" follows. Note that HO=F and RB=F are already on the next month's contract by then, so in the first days of each month the HO − gasoil gap compares different delivery months, and it can jump when the gasoil contract rolls. ICE publishes each settlement about 03:30 UTC the next day, so gasoil is added by the 12:15 SGT run. The API key is the repository secret `OILPRICEAPI_KEY` (Settings → Secrets and variables → Actions). Front-month series can jump on contract roll dates. Negative prices are kept (WTI settled below zero in April 2020).

## Data rules

- **History:** everything Yahoo has for each series (no cap). Each run merges the new download with the history already saved in `data/`, so the history only grows: if Yahoo ever returns a shorter history, the saved older days are kept (new values win where both exist). If a series switches to a fallback ticker, its history is not mixed with the old ticker's.
- **Calendar:** every weekday (Monday to Friday).
- **Missing dates** (holidays, or a market that hasn't reported yet): filled with the previous date's close, so that day counts as 0% for that index.
- **Failed download:** that index keeps its previous data, and the page shows a note.
- **Timing:** three scheduled runs: 05:15 SGT (indices and energy), 06:15 SGT (energy) and 12:15 SGT (energy, for the UK gasoil settlement). GitHub often starts scheduled runs late, sometimes by hours, so the script doesn't rely on the start time: it drops any trading day that hasn't closed yet in that market's own time zone. A late run therefore still saves only final closes. In US winter the 05:15 run is before the New York energy close, so the 06:15 run adds that day. Manual runs download everything.

## One-time setup (about 15 minutes)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a repository:** click **+** (top right) → **New repository**. Name it, for example `finance-tools`, and choose **Public** (free GitHub Pages needs a public repository). Click **Create repository**.
3. **Upload the files:** on the new repository page, click **uploading an existing file**. Drag in everything from this folder: `index.html`, `README.md`, and the `scripts` and `.github` folders (the `data` folder is created by the first run). Click **Commit changes**.
   - The `.github` folder is hidden on Mac and some Windows setups. If it doesn't upload, click **Add file → Create new file**, type `.github/workflows/update-data.yml` as the name, paste in the contents of that file, and commit.
4. **Turn on Pages:** go to **Settings → Pages**. Under **Build and deployment → Source**, choose **GitHub Actions**.
5. **Allow the workflow to save data:** go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and click **Save**.
6. **Run it the first time:** go to the **Actions** tab, click **Update index data and publish site**, then **Run workflow**. It takes about 1 to 3 minutes and downloads the full history.
7. **Open your site:** when the run shows a green tick, your page is at `https://<your-username>.github.io/finance-tools/`. Bookmark it.

After that, it updates itself every day at 05:15 SGT. You don't need to do anything.

## Good to know

- **Manual update:** Actions → Update index data and publish site → Run workflow.
- **If a run fails:** GitHub emails you. Open the run in the Actions tab to see which index failed. Usually it's a temporary Yahoo problem, and the next day's run fixes it.
- **If scheduled runs stop:** GitHub may pause scheduled workflows in repositories with no activity for 60 days. If you see a banner saying they were disabled, click **Enable workflow** in the Actions tab.
- **Changing the page:** edit `index.html` in GitHub (pencil icon) and commit. The site republishes automatically.
- **Adding an index:** add a line to `INDICES` in `scripts/update_data.py` with a key, name and Yahoo ticker, then commit.
