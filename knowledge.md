# Knowledge Base: ETF & Index Fund Ranking Project

This explains **everything** we built — the finance concepts and the technical
pipeline — from scratch. Written so a 15-year-old could follow it end to end.

---

## PART 1: The Finance — What Are We Even Doing?

### 1.1 What's an index?

Imagine you want to know "is the Indian stock market doing well today?" You
can't check all 5,000+ companies one by one. So smart people created
**indices** — a basket of specific stocks that represents a slice of the
market.

The most famous one is **NIFTY 50**: the 50 biggest, most-traded companies on
the NSE (National Stock Exchange of India), combined into one number. When
news says "Nifty is up 1%", it means those 50 companies, on average
(weighted by size), went up 1%.

There are hundreds of indices, each slicing the market differently:
- **NIFTY BANK** — only the big bank stocks
- **NIFTY IT** — only IT companies (TCS, Infosys, etc.)
- **NIFTY MIDCAP 150** — 150 mid-sized companies
- **S&P BSE SENSEX** — the BSE's (the other big Indian exchange) version of Nifty 50

An index itself is just a *number* — you can't actually buy "the Nifty 50."
It's like a scoreboard, not a product.

### 1.2 So how do you actually invest in an index?

Two products let you buy a basket that *tracks* an index's performance:

**ETF (Exchange Traded Fund)**
A fund that holds all the stocks in an index (e.g., all 50 Nifty 50 companies,
in the right proportions) and then is itself listed on the stock exchange —
you buy/sell it just like a share, with a ticker symbol (e.g. `NIFTYBEES`,
`SBINIFTY50`). Its price moves throughout the day along with the index.

**Index Fund**
Same idea (holds the basket of stocks to mirror an index), but it's a mutual
fund, not something you trade live on an exchange. You buy/sell units once a
day at a price set after market close (the NAV — see below). No ticker
symbol, no live trading.

Both are "passive" investing — nobody is picking stocks they *think* will do
well; the fund just mechanically copies the index. This is usually cheaper
and often performs as well as or better than "active" fund managers trying
to beat the market.

### 1.3 The key numbers that matter (and the jargon)

**AUM — Assets Under Management**
The total money currently invested in a fund, in ₹ (rupees), usually quoted
in **crore (cr)**. 1 crore = 10,000,000 (1 followed by 7 zeros) = ₹1,00,00,000.
If a fund's AUM is ₹68,029 cr, that means investors have put about
₹68,029,00,00,000 into it in total.

*Why it matters:* A bigger AUM generally means:
- The fund is trusted and established (lots of people already invested)
- It's less likely to be shut down (small funds sometimes get closed/merged)
- For ETFs specifically, bigger usually also means easier to buy/sell without
  moving the price much (see Liquidity below)

This project's core task was: **find the AUM of every ETF and index fund**,
because without it you can't tell "is this a serious, well-backed fund or a
tiny, risky one?"

**TER — Total Expense Ratio** (also called "Expense Ratio")
The annual fee the fund charges you, as a percentage of your investment. If
TER is 0.05%, and you have ₹1,00,000 invested, you pay about ₹50/year in
fees — automatically deducted, you never see a bill.

*Why it matters:* Over 10-20 years, fee differences compound a lot. A fund
charging 0.05% vs one charging 0.50% can mean a noticeably different amount
of money at the end, even if they track the exact same index. Lower TER is
generally better, *all else equal* — because a passive fund's whole job is to
copy the index, not beat it, so the fee is the main thing separating two
funds tracking the same index.

**Liquidity**
How easily you can buy or sell the ETF on the exchange without moving its
price. We used `Traded_Value` (how much rupee-value of the ETF trades per
day on NSE) as a proxy for this. A highly liquid ETF: you can buy/sell a big
chunk instantly at a fair price. A low-liquidity one: your own trade might
move the price against you, or you might struggle to find a buyer/seller.
(Index funds don't trade on an exchange, so this concept doesn't apply to
them — we leave liquidity blank for index funds.)

**NAV — Net Asset Value**
The "fair price" of one unit of a fund, calculated once a day: (total value
of everything the fund holds) ÷ (number of units). For index funds, this is
literally the price you transact at. For ETFs, NAV is the "fair value" but
the *traded price* on the exchange can drift slightly above or below it
during the day (supply and demand), which is one reason very liquid ETFs are
nicer to trade — the gap stays small.

**ISIN**
A unique ID code for a specific financial security (fund, stock, bond)
worldwide — like a serial number. We used it to match the same fund across
different data sources that might spell its name slightly differently.

**Tracking Error**
How closely a fund's returns actually match its index's returns. A perfect
copy would have 0% tracking error; in reality there's always a tiny gap
(fees, cash held, trading costs). We *didn't* use this in our ranking — it's
in your manually-compiled list, but it's complex to get cleanly for free
across hundreds of funds, so we treated it as a "nice to have, not now."

### 1.4 The actual goal, restated simply

> "Give me, for every index that has at least one real ETF/index fund
> tracking it, the top 2-3 biggest/best options — but only count funds with
> at least ₹10 crore AUM, because anything smaller is too new/risky/illiquid
> to take seriously."

And: do it twice — once ranked purely by size (AUM), and once ranked by a
blend of size + cost (TER) + tradability (liquidity), because "biggest" and
"best value" aren't always the same fund.

---

## PART 2: The Technical Side — How We Built It

### 2.1 The core problem: no single source has everything

This was the hardest part of the whole project. There's no one website or
government file that says "here is every ETF and index fund, with its
current AUM, in one table." So we had to **stitch together 5 different data
sources**, each giving us one piece of the puzzle:

| Source | What it gave us | What it's missing |
|---|---|---|
| **NSE (stock exchange) API** | List of all ~140 indices, all ~360 ETFs with live trading data (price, volume) | No AUM, no TER |
| **AMFI** (the official mutual fund industry body in India) | List of every mutual fund scheme (including index funds), with NAV | AUM only at the *fund house* level (e.g. "all of SBI's funds combined"), not per individual fund |
| **NiftyIndices.com** | Official codes mapping index names to benchmarks | — |
| **Trendlyne** (a financial data website) | Bulk AUM + TER for ~300 ETFs in one go | Doesn't include the biggest ~50 ETFs (SBI, NIFTYBEES, etc. — for reasons we never figured out, possibly a premium-tier gate) |
| **Groww / Tickertape** (investing apps) | Per-fund AUM + TER, one fund at a time, via their public (undocumented) APIs | Slow (one web request per fund), and Tickertape started blocking us after too many requests |
| **You, manually** | AUM/TER for the ~22-25 biggest ETFs that nothing else gave us | Took your time, but 100% reliable for the funds that matter most |

### 2.2 The pipeline, step by step

Think of this as an assembly line. Each step produces a file that the next
step reads. All the raw data lives in `data/`, all the code lives in
`ranking/` (plus the older gathering script `fetch_etf_index_data.py` at the
project root).

**Step 1 — Gather raw data** (`fetch_etf_index_data.py`, runs once)
- Downloads every NSE index → `data/01_nse_indices.csv`
- Downloads every NSE-listed ETF with live price/volume → `data/02_nse_etfs.csv`
- Downloads every AMFI mutual fund scheme and filters to ETFs/index funds → `data/03_amfi_etf_index_schemes.csv`
- Downloads the official index benchmark codes → `data/04_benchmark_codes.csv`
- A supplementary scheme list from a community API → `data/05_mfapi_schemes.csv`
- **Matches each fund's name to the index it tracks** using pattern-matching
  (e.g. a fund named "...NIFTY50 INDEX FUND..." gets matched to the "NIFTY 50"
  index) → `data/06_mapped_funds.csv`. This file has ~2,372 rows at this
  point — more than the real number of funds, because of the next problem...

**Step 2 — Clean up duplicates** (`ranking/dedup.py`)
Every mutual fund actually exists as *multiple* near-identical database rows:
"Direct Plan + Growth option", "Direct Plan + Dividend option", "Regular Plan
+ Growth option", "Regular Plan + Dividend option" — same fund, 4 rows. ("Direct"
means you invest straight with the fund company, no middleman commission —
usually has a lower TER than "Regular," which goes through an
advisor/distributor who takes a cut.)

We collapse these down to **one row per actual fund**, always preferring the
Direct + Growth version (cheapest, and the one that reinvests gains rather
than paying them out). This took us from 2,372 rows down to **632 real
funds**: 283 ETFs + 349 index funds.

We also decided (after checking with you) to only keep funds tracking **NSE
and BSE** indices — dropping international indices (Nasdaq 100, S&P 500,
MSCI, FTSE — these track *foreign* markets, a different kind of bet) and
CRISIL indices (these track bonds/debt, not stocks — a totally different
asset class from what this project is about). That left **587 funds**.

**Step 3 — Get the AUM and TER for each fund** (`ranking/aggregator.py`,
`ranking/trendlyne.py`, `ranking/manual_overrides.py`, `ranking/enrich.py`)

For each of the 587 funds, we need its AUM (required) and TER (nice to
have). We try sources **in priority order**, stopping at the first one that
gives us a confident answer:

1. **Your manual data** (`data/manual_etf_overrides.csv`) — always wins if present, since you personally verified it
2. **Trendlyne's bulk ETF table** — for ETFs, one API call fetches ~50 funds at once (we page through it 7-8 times to get everyone); fast and not rate-limited
3. **Tickertape** — for ETFs Trendlyne missed; one API call per fund, and it started **blocking us (HTTP 403 "rate limit exceeded")** after a few hundred rapid calls, like a bouncer kicking you out of a club for showing up too many times
4. **Groww** — for index funds (Trendlyne/Tickertape don't cover these well); also one call per fund

Why "cache" matters here: every answer we successfully get is saved to
`data/08_aum_ter.csv`. If we re-run the pipeline, already-answered funds are
**not** re-fetched — only the still-unknown ones get retried. This is why,
across several runs, our coverage kept climbing (5% → 91% → 99% for ETFs)
without wasting time re-asking questions we already had answers to.

**Step 4 — Filter and rank** (`ranking/rank.py`)

Now that every fund (hopefully) has an AUM number, we:
1. **Filter**: throw out anything with AUM < ₹10 crore (your rule) — these go
   to a "Below 10cr" list, not deleted, just set aside
2. **Rank by AUM** (Ranking A): for each index, sort its funds biggest-AUM-first
3. **Rank by a composite score** (Ranking B): for each index, blend three
   numbers into one score:
   - 50% weight on AUM (bigger = better)
   - 30% weight on TER (lower = better)
   - 20% weight on Liquidity (higher = better, ETFs only)

   To combine numbers that are on totally different scales (AUM in crores,
   TER in tiny percentages, Liquidity in rupees traded), we **normalize**
   each one first — within its own index, rescale every fund's value to a
   0-to-1 scale (worst fund = 0, best fund = 1), *then* take the weighted
   average. This is called **min-max normalization**. It's the standard
   trick for comparing apples to oranges fairly.

   If a fund is missing TER or liquidity, we don't penalize it unfairly —
   we just drop that piece and re-split the weight across whatever data we
   do have (e.g., missing TER → score becomes 100% AUM + liquidity only,
   reweighted to still sum to 100%).

**Step 5 — Build the final spreadsheet** (`ranking/build_output.py`,
`run_ranking.py` ties it all together)

Everything gets written into one Excel file: `data/07_final_shortlist.xlsx`,
with multiple tabs (sheets) — see Part 3 below for how to read it.

### 2.3 Key technical terms explained

**API** — a way for two computer programs to talk to each other over the
internet. When we "call the Trendlyne API," our code sends a request (like
"give me page 1 of your ETF table") and gets back structured data (usually
JSON — see below) instead of a pretty webpage.

**JSON** — a simple text format for structured data, like a more compact,
computer-friendly spreadsheet row. Looks like
`{"symbol": "NIFTYBEES", "aum": 68029.38}`.

**Scraping** — extracting data from a website/API that wasn't necessarily
built to be a public data feed. We had to reverse-engineer how Trendlyne's
own webpage internally fetches its ETF table data, then call that same
internal link ourselves.

**Rate limiting** — a website protecting itself from being hit with too many
requests too fast (looks like a robot/bot attack otherwise). Tickertape's
403 block was this — we were asking it 632 questions rapidly, and it decided
that was suspicious and cut us off for a while.

**Cache** — saving an answer so you don't have to look it up again. Our
`data/08_aum_ter.csv` is exactly this: a running memory of every fund's
answer, reused on every future run.

**CSV** — "Comma-Separated Values," the simplest possible spreadsheet file
format: plain text, one row per line, columns separated by commas. Almost
every data file in `data/` is one of these.

**Unit testing** — before trusting a piece of code, we write small automated
checks that feed it known inputs and verify it produces the known-correct
output (e.g., "if AUM is exactly ₹10 cr, does the filter correctly keep it?
if it's ₹9.99 cr, does it correctly drop it?"). We wrote 29 of these for this
project (`tests/` folder) — they all still pass today, meaning the core
logic is verified correct, independent of whether any particular website's
data is accurate.

**Git / commits / branch** — a system for tracking every change we made to
the code over time, like a very detailed "undo history" with notes
explaining *why* each change was made. Every meaningful step of this project
is a separate, labeled commit, so the full history is inspectable later if
needed.

---

## PART 3: How to Read and Analyze `data/07_final_shortlist.xlsx`

Open the file in Excel/Google Sheets/Numbers. It has these tabs (bottom of
the window):

### `Summary`
The one-glance health check. As of the last run:
- **Qualifying funds: 515** — funds that passed the ₹10cr AUM filter and are in the rankings
- **Indices with ≥1 qualifying fund: 82** — how many different indices have at least one investable option
- **Unresolved AUM: 26** — funds where we genuinely couldn't find an AUM number (mostly very new funds or small index funds with no matching data online). They are *not* in the rankings, and not assumed to have failed the filter — we just don't know.
- **Below 10cr: 46** — funds we *did* find AUM for, but it was too small, so they were filtered out
- **Composite weights (AUM/TER/liq): 0.5/0.3/0.2** — reminder of how Ranking B was calculated

### `Top 3 by AUM` ← probably the most useful tab for a quick answer
For every index, the top 3 biggest funds. Read it like: "for NIFTY 50, the
three biggest options are SBI Nifty 50 ETF (₹2,03,017 cr), UTI Nifty 50 ETF
(₹71,670 cr), Nippon India ETF Nifty 50 BeES (₹68,029 cr)." Simple and
decisive — "I want the safest, most-established choice" → pick rank 1 here.

### `Top 3 by Composite` ← the "best value" view
Same idea, but ranked by the blended score (size + low cost + tradability),
not just raw size. Sometimes this reorders things — a fund that's smaller
but noticeably cheaper (lower TER) or more liquid might outrank a bigger,
pricier one. Use this tab when you care about long-term cost, not just "is
this the famous/biggest one."

**How to sanity-check a result here:** look at the `aum_norm`, `ter_norm`,
`liq_norm` columns (0 to 1 each) alongside `composite_score`. If a fund has a
high overall score but you want to know *why*, these show which factor
(size, cost, or tradability) is driving it.

### `Rank by AUM` and `Rank by Composite`
The full tables (not just top 3) — every qualifying fund, every index,
fully ranked. Use these if you want to see, say, the #5 or #10 option for a
specific index, or to filter/sort yourself in Excel.

### `Unresolved AUM`
Funds we couldn't get a number for. Worth skimming if you're deciding
whether to manually research one of them — e.g. if a new, important-looking
ETF launched recently and its index matters to you.

### `Below 10cr`
Funds that are real and have an AUM number, but it's small (< ₹10 cr).
Useful if you ever want to loosen the filter and see what you're excluding.

### `All NSE Indices` and `Benchmark Codes`
Reference data — the full index list and the official codes, in case you
want to cross-check an index name or look something up independently.

### A practical way to use this file

1. **Decide what you're trying to answer.** "What's the biggest/safest Nifty
   50 ETF?" → `Top 3 by AUM`, filter the `matched_index` column to "NIFTY 50",
   look at rank 1.
2. **If cost matters to you long-term** (you're planning to hold for years),
   prefer `Top 3 by Composite` instead — it already factors in TER for you.
3. **Don't treat "rank 1" as gospel.** AUM and TER are good signals, but this
   project deliberately did *not* include tracking error or fund manager
   track record — those are reasonable things to check yourself before
   actually investing real money. Think of this spreadsheet as a well-
   informed shortlist, not a final verdict.
4. **Check the `aum_source` / `ter_pct` for any fund you're seriously
   considering** (visible in `Rank by AUM`/`Rank by Composite`) — if it says
   "manual," that's a number you (or I, from your research) typed in by
   hand; worth double-checking against the AMC's own factsheet before
   relying on it for a real decision, since scraped/manual numbers can go
   stale.

---

## Quick Glossary (all the jargon in one place)

| Term | Plain-English meaning |
|---|---|
| Index | A basket of stocks used as a scoreboard for a slice of the market (e.g. Nifty 50) |
| ETF | A basket-of-stocks fund that trades live on the stock exchange like a share |
| Index Fund | A basket-of-stocks fund you buy/sell once a day at a set price (no live trading) |
| AUM | Total money invested in a fund (its "size"), usually in ₹ crore |
| Crore | 1,00,00,000 (ten million) |
| TER / Expense Ratio | The annual fee % the fund charges you |
| NAV | The "fair price" of one unit of a fund |
| Liquidity | How easily you can buy/sell without moving the price |
| ISIN | A unique worldwide ID code for a specific fund/security |
| Tracking Error | How closely a fund actually matches its index's performance |
| Direct Plan | Buying a fund straight from the company — usually cheaper |
| Regular Plan | Buying through an advisor/distributor — usually costs a bit more |
| Passive investing | Just copying an index, not trying to pick winning stocks |
| API | How two programs fetch data from each other over the internet |
| JSON | A simple structured-text data format |
| Scraping | Extracting data from a site/API not officially meant to be a public feed |
| Rate limiting | A website blocking you for asking it too many questions too fast |
| Cache | Saving an already-found answer so you don't re-fetch it |
| CSV | A plain-text spreadsheet file format |
| Normalization | Rescaling different numbers (₹, %, etc.) onto the same 0-to-1 scale so they can be fairly combined |




Setup (once)
Fill in both keys in screener/secrets_local.py, which git ignores:
KITE_API_KEY = "…"
KITE_API_SECRET = "…"

The file currently holds placeholders. Enter the keys there directly, not in this chat.

Set the Redirect URL: in the Kite developer console, set your app’s Redirect URL to http://127.0.0.1. That’s simply where Zerodha sends you after login, and it’s easy to copy from the browser’s address bar.
Daily routine
Open the app and click Login with Zerodha. Zerodha’s login page opens in your browser.
Log in with your password and 2FA.
The browser lands on an address like http://127.0.0.1/?…&request_token=…. The page itself will show an error, which is expected. Copy the whole address from the address bar.
Paste it into the box and click Connect. The app swaps it for today’s access token, loads any missing history and goes live.

The same box still accepts a ready-made access token, if you ever have one.

How it behaves
The access token stays in memory only. The box clears after you click Connect.
Each login address works once. If it’s reused or too old, the app says so in red and asks you to log in again.
Without a secret, the login button is disabled. The self-test now reports whether the secret is set.
Before you share the .exe

Both keys get built into the .exe, and anyone who has the file can extract them. On their own they don’t open your account, because a login still needs your Zerodha password and 2FA. After you add your real keys, rebuild with: