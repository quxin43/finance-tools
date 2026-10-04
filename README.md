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
| GO | UK gasoil (ICE) | 7F=F, GX=F (to be confirmed) | USD/t | ÷ 7.45 |

Saved in `data/energy.json`. Front-month series can jump on contract roll dates. Negative prices are kept (WTI settled below zero in April 2020).

## Data rules

- **History:** as far back as Yahoo has each index, capped just under 30 years.
- **Calendar:** every weekday (Monday to Friday).
- **Missing dates** (holidays, or a market that hasn't reported yet): filled with the previous date's close, so that day counts as 0% for that index.
- **Failed download:** that index keeps its previous data, and the page shows a note.
- **Timing:** two scheduled runs. 05:15 SGT (21:15 UTC) downloads the indices every day. The energy futures are downloaded inside the NYMEX daily break (17:00–18:00 New York): by the 05:15 SGT run when the US is on summer time, and by the 06:15 SGT run (22:15 UTC) in winter. The script checks New York time itself, so daylight-saving changes are handled automatically. Manual runs download everything. Each run re-downloads the full history, so a late or skipped day is corrected by the next run.

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
