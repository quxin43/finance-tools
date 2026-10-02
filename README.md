# Finance tools with daily index data

Three tabs: **Dip ladder**, **Rally ladder** and **Index gap**. A GitHub workflow downloads daily closes for 13 indices from Yahoo Finance every day at **06:00 Singapore time** and republishes the site, so the Index gap tab is always current.

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

## Data rules

- **History:** as far back as Yahoo has each index, capped just under 30 years.
- **Calendar:** every weekday (Monday to Friday).
- **Missing dates** (holidays, or a market that hasn't reported yet): filled with the previous date's close, so that day counts as 0% for that index.
- **Failed download:** that index keeps its previous data, and the page shows a note.
- **Timing:** 06:00 SGT is 22:00 UTC, after the US close (the last of these markets to close). GitHub sometimes starts scheduled jobs a few minutes to an hour late.

## One-time setup (about 15 minutes)

1. **Create a GitHub account** at github.com if you don't have one.
2. **Create a repository:** click **+** (top right) → **New repository**. Name it, for example `finance-tools`, and choose **Public** (free GitHub Pages needs a public repository). Click **Create repository**.
3. **Upload the files:** on the new repository page, click **uploading an existing file**. Drag in everything from this folder: `index.html`, `README.md`, and the `scripts` and `.github` folders (the `data` folder is created by the first run). Click **Commit changes**.
   - The `.github` folder is hidden on Mac and some Windows setups. If it doesn't upload, click **Add file → Create new file**, type `.github/workflows/update-data.yml` as the name, paste in the contents of that file, and commit.
4. **Turn on Pages:** go to **Settings → Pages**. Under **Build and deployment → Source**, choose **GitHub Actions**.
5. **Allow the workflow to save data:** go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and click **Save**.
6. **Run it the first time:** go to the **Actions** tab, click **Update index data and publish site**, then **Run workflow**. It takes about 1 to 3 minutes and downloads the full history.
7. **Open your site:** when the run shows a green tick, your page is at `https://<your-username>.github.io/finance-tools/`. Bookmark it.

After that, it updates itself every day at 06:00 SGT. You don't need to do anything.

## Good to know

- **Manual update:** Actions → Update index data and publish site → Run workflow.
- **If a run fails:** GitHub emails you. Open the run in the Actions tab to see which index failed. Usually it's a temporary Yahoo problem, and the next day's run fixes it.
- **If scheduled runs stop:** GitHub may pause scheduled workflows in repositories with no activity for 60 days. If you see a banner saying they were disabled, click **Enable workflow** in the Actions tab.
- **Changing the page:** edit `index.html` in GitHub (pencil icon) and commit. The site republishes automatically.
- **Adding an index:** add a line to `INDICES` in `scripts/update_data.py` with a key, name and Yahoo ticker, then commit.
