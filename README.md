# Finance tools with daily index data

Eight tabs: **Dip ladder**, **Rally ladder**, **Inv Ratio**, **Index gap**, **Index ratio**, **Energy gap**, **Metal ratio** and **Agri gap**. A GitHub workflow downloads daily closes for 13 indices from Yahoo Finance every day at **05:15 Singapore time** (energy futures at 05:15 or 06:15 depending on US daylight saving) and republishes the site, so the Index gap tab is always current.

## Peaks and bottoms panel (Index gap tab)

For one index (default US500): a **peak** is a close higher than the *n* trading days before and after it, a **bottom** a close lower than them (default n = 5, adjustable). Two peaks in a row keep the higher one, two bottoms the lower, so they alternate. Each fall is annualised as **Ln = (Bn ÷ Pn − 1) × 365 ÷ days** and each rise as **Gn = (Pn+1 ÷ Bn − 1) × 365 ÷ days** (calendar days). The panel shows the price coloured by leg, a chart of Ln (red) and Gn (green) as bars across each leg's dates (clipped at ±300% a year), counts and medians for the chosen range, and the current unconfirmed leg (dashed).

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

## Index ratio tab

Uses the same daily index closes as the Index gap tab (data/indices.json), so it needs no extra download. Pick a start date (or a quick range) and two indices; the ratio is index A points ÷ index B points on each day. The summary shows both latest closes, the ratio on the last date, its average, highest, lowest and standard deviation (σ) over the range, and how many σ the latest ratio is from the average (pink beyond 2σ, red beyond 3σ), as on the Energy gap tab. The chart can also show both indices (one price axis each) and Bollinger Bands (20 days, ±2σ); below it, MACD (12, 26, 9), RSI (14) and KDJ (9, 3, 3) of the ratio, computed over the pair's whole common history so the start date doesn't change them. Settings are kept in the browser (localStorage key finmon-iratio-v1).

## Energy futures (Energy gap tab)

| Key | Market | Yahoo ticker | Native unit | Saved as USD/bbl |
|---|---|---|---|---|
| BRENT | Brent crude | BZ=F | USD/bbl | as is |
| WTI | WTI crude (Texas) | CL=F | USD/bbl | as is |
| HO | US heating oil | HO=F | USD/gal | × 42 |
| RB | US gasoline (RBOB) | RB=F | USD/gal | × 42 |
| GO | UK gasoil (ICE Low Sulphur Gasoil) | OilPriceAPI `GASOIL_USD` (not on Yahoo) | USD/t | ÷ 7.45 |

Saved in `data/energy.json`. UK gasoil comes from [OilPriceAPI](https://www.oilpriceapi.com) on the free plan (50 requests a day; each run uses 1 or 2), using ICE's official daily settlements from 24 March 2026, and the history grows from there. (OilPriceAPI's older "gasoil" data turned out to be US heating oil in USD/gal, so the script rejects any value below 200 USD/t. It also removes one-day spikes: a day more than 8% away from both neighbours while they agree, or more than 15% away from both.) The contract used on each date is the nearest one still trading (for example October until it expires around 12 October, then November), the same contract CMC's "Low Sulphur Gasoil - Cash" follows. Note that HO=F and RB=F are already on the next month's contract by then, so in the first days of each month the HO − gasoil gap compares different delivery months, and it can jump when the gasoil contract rolls. ICE publishes each settlement about 03:30 UTC the next day, so gasoil is added by the 14:15 SGT run. The API key is the repository secret `OILPRICEAPI_KEY` (Settings → Secrets and variables → Actions). Front-month series can jump on contract roll dates. Negative prices are kept (WTI settled below zero in April 2020).

## Futures curve tables (Energy gap tab)

Under each energy chart, a table shows the next 12 contract months traded by both legs, with each month's latest settlement in USD/bbl, the gap and the ratio. Brent, WTI, heating oil and gasoline come from Yahoo's monthly NYMEX tickers (for example `HOX26.NYM` = heating oil, November 2026; month codes F G H J K M N Q U V X Z = Jan to Dec); UK gasoil comes from the OilPriceAPI data the run already downloads. The months are worked out on every run from each exchange's expiry rule, so when the nearest contract expires it drops off and a new month is added at the end. The table also shows each contract's volume (contracts traded on the settlement day) and open interest (contracts still open); open interest comes from Yahoo's quote details and is not available for gasoil. Saved in `data/curve.json` (only the latest curve; no history). The gap charts themselves still use the continuous tickers (BZ=F, CL=F, HO=F, RB=F).

## Inv Ratio tab

A calculator for a two-leg ratio trade, with no market data. Enter the price ratio now, p_ri = pA / pB, a best-case final ratio p_rfb, a worst-case final ratio p_rfw, and a range for A's final price pA'/pA (default 0.5 to 2). If p_rfb is below p_ri the trade is short A / long B; if above, long A / short B. For each final price of A, B's final price follows from the final ratio: pB'/pB = (pA'/pA) × p_ri / p_rf.

The chart plots gain (% of 10,000) against the split iA, from −1 (10,000 short A) through 0 (10,000 in B) to +1 (10,000 long A); the rest, (1 − |iA|) × 10,000, is in B on the side the trade direction sets. Five colours are five final prices of A; solid lines are the best-case ratio, dashed the worst. All dashed lines cross at one split: there the worst-case result is fixed whatever the price level, and the summary shows that split, the fixed result, and the best-case range for the same split (and the same for the best-case crossing). Inputs are kept in the browser (localStorage key finmon-inv-v2). Ignores fees, funding, margin and contract sizes.

## Metal ratio tab

Four ratio charts, each with average, ±2σ and ±3σ bands like the energy charts, both prices on their own right-hand axes, and a futures-curve table:

- **Gold ÷ silver**: ounces of silver one ounce of gold buys.
- **Gold ÷ platinum**: platinum's discount to gold.
- **Platinum ÷ palladium**: the car-catalyst substitution pair.
- **Copper ÷ gold** (copper USD/lb ÷ gold USD/oz × 1,000): growth-versus-safety gauge; tends to move with the US 10-year yield.

Front-month continuous futures from Yahoo (`GC=F` gold, `SI=F` silver, `HG=F` copper on COMEX; `PL=F` platinum, `PA=F` palladium on NYMEX), downloaded on every run together with energy and saved in `data/metals.json` (full history, kept and extended like the other series). Gold, silver, platinum and palladium are in USD per troy ounce, copper in USD per pound.

The futures-curve tables use Yahoo's monthly tickers (for example `GCZ26.CMX`, `PLF27.NYM`) and are saved in `data/metal_curve.json`. Metals list different months (gold Feb/Apr/Jun/Aug/Oct/Dec, silver Jan/Mar/May/Jul/Sep/Dec, platinum Jan/Apr/Jul/Oct, palladium Mar/Jun/Sep/Dec, copper every month, all of them the nearest few months), so where only one metal of a pair has a contract the page estimates the other metal's price between its neighbouring contracts and marks it "≈". Last trading day: third-last business day of the delivery month.

## Agri gap tab

Four panels from US contracts traded on CMC, each with a Gap/Ratio switch, the usual average and σ bands, and a futures-curve table:

- **Soybeans ÷ corn** (default ratio): the US planting signal; new-crop November soybeans ÷ December corn above about 2.4 favours soybeans, below about 2.2 corn.
- **Wheat − corn** (cents per bushel): feed-substitution spread.
- **Soybean crush** = soybean meal (USD/short ton) × 2.2 + soybean oil (¢/lb) × 11 − soybeans (¢/bu): the processors' margin per bushel, in cents.
- **Soybean oil − heating oil (BOHO)**, USD per gallon (soybean oil ¢/lb × 7.5 ÷ 100): the biodiesel margin gauge.

Front-month continuous futures from Yahoo (`ZS=F`, `ZC=F`, `ZW=F`, `ZM=F`, `ZL=F` on CBOT; `HO=F` on NYMEX), saved in `data/agri.json` together with the computed crush value (`SOYPROD`) and soybean oil per gallon (`BOGAL`). Contract months come from Yahoo's monthly tickers (for example `ZSX26.CBT`) and are saved in `data/agri_curve.json`; months only one leg trades are estimated ("≈") as on the Metal ratio tab. Last trading day for CBOT contracts: the business day before the 15th of the delivery month.

Not included: London white sugar, robusta coffee and UK cocoa (the other side of the popular sugar, coffee and cocoa spreads) are not on Yahoo Finance.

## Data rules

- **History:** everything Yahoo has for each series (no cap). Each run merges the new download with the history already saved in `data/`, so the history only grows: if Yahoo ever returns a shorter history, the saved older days are kept (new values win where both exist). If a series switches to a fallback ticker, its history is not mixed with the old ticker's.
- **Calendar:** every weekday (Monday to Friday).
- **Missing dates** (holidays, or a market that hasn't reported yet): filled with the previous date's close, so that day counts as 0% for that index.
- **Failed download:** that index keeps its previous data, and the page shows a note.
- **Timing:** four runs a day, each updating indices and energy: 05:15 SGT and 06:15 SGT (after the US close in summer and in winter time), 14:15 SGT (final settlements for the previous day, including UK gasoil) and 21:45 SGT in US summer time / 22:45 SGT in US winter time (US and European markets both open; GitHub schedules are in UTC, so both are scheduled and the script skips the one that doesn't match). GitHub often starts scheduled runs late, sometimes by an hour or more. The latest day of each Yahoo series may be a live price if its market is still trading when the run starts; the page marks those with a LIVE tag and shows when the data was last updated, in Singapore time. Every run re-downloads the full history, so earlier days always end up with their final closes. UK gasoil only uses ICE's official settlement, published about 03:30 UTC the next day.

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

## "Update data now" button (one-click update)

The button at the top right starts the GitHub update straight away, waits for it (about 3 minutes) and reloads the page. It needs a GitHub token saved in your browser:

1. GitHub → your profile picture → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Name it (for example "finance-tools update"), pick an expiry, and under **Repository access** choose **Only select repositories → finance-tools**.
3. Under **Permissions → Repository permissions**, set **Actions** to **Read and write** (Metadata read-only is added automatically). Nothing else.
4. Generate, copy the token, then on the site click **⚙** next to the button and paste it.

The token is kept only in that browser (localStorage) and sent only to api.github.com. It can do nothing except start and read workflow runs of this repository. Use ⚙ and leave it empty to remove it. Without a token, the button opens the Actions page, where you can click **Run workflow** yourself.

## Indicators on the Index gap tab

Below the A − B chart (checkbox "Show indicators"): **Bollinger Bands** (20-day average ± 2σ, drawn on the gap chart, with %B), **MACD** (12, 26, 9), **RSI** (14, Wilder) and **KDJ** (9, 3, 3, close-only). All are calculated on the gap A − B over the pair's whole common history, so they don't depend on the start date.

## Good to know

- **Manual update:** Actions → Update index data and publish site → Run workflow.
- **If a run fails:** GitHub emails you. Open the run in the Actions tab to see which index failed. Usually it's a temporary Yahoo problem, and the next day's run fixes it.
- **If scheduled runs stop:** GitHub may pause scheduled workflows in repositories with no activity for 60 days. If you see a banner saying they were disabled, click **Enable workflow** in the Actions tab.
- **Changing the page:** edit `index.html` in GitHub (pencil icon) and commit. The site republishes automatically.
- **Adding an index:** add a line to `INDICES` in `scripts/update_data.py` with a key, name and Yahoo ticker, then commit.
