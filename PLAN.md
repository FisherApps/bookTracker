# Amazon BSR Tracker — Implementation Plan (v2)

## Context

I'm building a personal tool to track Amazon Best Sellers Rank (BSR) over time
for my dad's books (he's an author, ~100 titles total, starting with 35). One
snapshot per book per day, stored locally, used to build visualizations later.
I'm an iOS engineer — frontend is not the concern, getting reliable data is.

This plan covers **data acquisition and storage only**. Dashboard / hosting will
be handled separately by me later.

## Non-goals (do not build)

- Dashboard, web UI, or visualization code
- Cloud deployment, Docker, CI/CD
- Keepa, RainforestAPI, or any third-party paid data source
- Auto-discovery of new books from author pages (the book list is a hand-edited
  file — see "Book registry" below)
- User accounts, auth, multi-user anything
- Any database other than SQLite
- Any scraping framework heavier than `requests` + `beautifulsoup4` for the
  first version (no Playwright, Selenium, Scrapy)
- Sub-category change detection, historical backfill, or any other "nice to
  have" beyond what's listed in this plan

## Success criteria

1. I can drop a list of ASINs in a config file and run one command to fetch
   today's ranks for all of them.
2. Each successful fetch appends a row per rank to a SQLite database.
3. CAPTCHA / blocked responses are detected and logged as failures, **never**
   parsed as if they were product pages.
4. There is a `--dry-run` mode that fetches and parses but does not write to the
   database.
5. There is a `reparse` mode that re-parses saved HTML files instead of
   fetching, so the parser can be developed and tested offline.
6. There is a test suite for the parser using saved HTML fixtures.
7. I can re-run the scraper for the same day safely without creating duplicate
   rows.

## Environment

- Python 3.11 or later. Use modern features freely — dataclasses with `slots`,
  `Literal`, `match` statements are all fine.
- macOS or Linux. Don't worry about Windows-specific path handling.
- `requirements.txt` should pin loose ranges so things don't break in a year:
  ```
  requests>=2.31,<3
  beautifulsoup4>=4.12,<5
  pytest>=8,<9
  ```
  Nothing else. If you find yourself wanting another dependency, the plan is
  wrong — flag it instead of adding it.

## Project layout

```
bsr-tracker/
├── README.md                       # how to install, run, add books, back up
├── requirements.txt                # pinned ranges (see above)
├── books.json                      # the book registry (hand-edited; I'll provide seed)
├── bsr.db                          # SQLite database (created on first run)
├── discovered_titles.txt           # see "Title discovery" below
├── poc_parser.py                   # reference parser from PoC; do not import, just read
├── logs/
│   └── run-YYYY-MM-DD.log          # one log file per run
├── fixtures/
│   └── jfk.html                    # I will copy this in by hand before tests run
├── src/
│   ├── __init__.py
│   ├── fetch.py                    # HTTP fetching, CAPTCHA detection
│   ├── parse.py                    # HTML → structured rank data
│   ├── db.py                       # SQLite schema, inserts, queries
│   ├── scrape.py                   # orchestrates fetch + parse + write, CLI entry
│   └── reparse.py                  # re-parse from saved HTML files, CLI entry
└── tests/
    ├── test_parse.py               # parser correctness on fixtures
    └── test_db.py                  # schema, dedupe, basic queries
```

Keep dependencies to exactly: `requests`, `beautifulsoup4`, `pytest`. Nothing
else.

## Book registry: `books.json`

Hand-edited JSON file, source of truth for which books to track.

```json
[
  {
    "asin": "B0GY7T45YS",
    "title": "The Life of John Kennedy",
    "active": true,
    "notes": "Presidential Chronicles series"
  }
]
```

Rules:
- `asin` is the only field the scraper requires; everything else is for me.
- `active: false` → skip during scrape but keep in file for history.
- The scraper loads this file at the start of each run. Do not store the book
  list in the database — the JSON file is the source of truth.
- I will provide the seed file with 35 ASINs (mostly with empty `title` fields)
  before the first run.

### Title discovery

Because seeding `books.json` titles by hand for 35+ books is annoying, the
scraper helps:

- On every successful fetch of a book whose `books.json` entry has an empty
  `title`, append a line to `discovered_titles.txt` in the format:
  ```
  B0GY7T45YS  The Life of John Kennedy
  ```
- Only append if the ASIN isn't already in the file (read once at start of run,
  keep a set in memory, write at end). Don't overwrite the file, don't modify
  `books.json` directly — I'll paste titles back in by hand when I feel like it.

## Database schema (SQLite)

One file: `bsr.db`. Two tables.

### `snapshots`

One row per (book, category) per fetch. The "overall" Books rank is stored as
just another row with `category_id = 'books'` so the schema is uniform.

```sql
CREATE TABLE snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asin          TEXT    NOT NULL,
    captured_at   TEXT    NOT NULL,           -- ISO 8601 UTC, e.g. '2026-05-25T04:00:00+00:00'
    capture_date  TEXT    NOT NULL,           -- 'YYYY-MM-DD' in UTC, derived; used for dedupe
    category_id   TEXT    NOT NULL,           -- 'books' for overall, else Amazon's numeric ID as string
    category_name TEXT    NOT NULL,           -- 'Books' or e.g. 'United States History (Books)'
    rank          INTEGER NOT NULL,           -- 1 = best
    UNIQUE (asin, capture_date, category_id)  -- one snapshot per book/category/day
);

CREATE INDEX idx_snapshots_asin_date ON snapshots (asin, capture_date);
CREATE INDEX idx_snapshots_category   ON snapshots (category_id, capture_date);
```

The `UNIQUE` constraint is how we get idempotent re-runs. Insert with
`INSERT OR IGNORE` — re-running on the same day is a no-op for already-captured
books.

**Time zone note:** `capture_date` is UTC, not local. This means if the scraper
runs at 11 PM Eastern and again at 2 AM Eastern the next morning, those land on
different UTC dates and *both* will insert rows. That's fine — I'll just be
disciplined about running it once a day. Not worth solving.

**Category name format:** store exactly what Amazon displays, including any
trailing `(Books)` suffix or other parenthetical. Don't normalize, don't strip.
I'll clean up in queries if I ever need to.

### `failures`

```sql
CREATE TABLE failures (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asin          TEXT    NOT NULL,
    attempted_at  TEXT    NOT NULL,           -- ISO 8601 UTC
    reason        TEXT    NOT NULL,           -- one of: 'http_error', 'captcha', 'no_rank_block', 'parse_error', 'timeout'
    http_status   INTEGER,                    -- nullable; present for http_error
    detail        TEXT                        -- short error string, optional
);

CREATE INDEX idx_failures_asin_date ON failures (asin, attempted_at);
```

No `UNIQUE` constraint on failures — multiple failure rows per day for the same
book are fine (initial + retry).

## Fetching: `src/fetch.py`

Public function: `fetch_product_html(asin: str, session: requests.Session) -> FetchResult`

Where `FetchResult` is a small dataclass with fields:
- `asin: str`
- `status: Literal['ok', 'http_error', 'captcha', 'timeout']`
- `http_status: int | None`
- `html: str | None`          # populated only when status == 'ok'
- `reason_detail: str | None`

### Requirements

- URL format: `https://www.amazon.com/dp/{ASIN}` (the bare canonical form; do
  not preserve query parameters from anywhere else).
- Send realistic headers. Use a recent desktop Chrome User-Agent string. Include
  at minimum: `User-Agent`, `Accept`, `Accept-Language: en-US,en;q=0.9`,
  `Accept-Encoding`. Do **not** send `python-requests`'s default UA.
- Timeout: 20 seconds total.
- The caller owns the `requests.Session()` and passes it in, so cookies persist
  across the run's requests (more human-like, fewer challenges).
- **CAPTCHA detection** (critical — see "What 'success' means" below):
  - If response status is 503, mark as `captcha`.
  - If response body contains any of: `"Type the characters you see in this image"`,
    `"To discuss automated access to Amazon data please contact"`,
    `"Sorry, we just need to make sure you're not a robot"`,
    `"api-services-support@amazon.com"` → mark as `captcha`.
  - If response status is 200 but the body does **not** contain the literal
    string `"Best Sellers Rank"` → mark as `captcha` with detail
    `"missing_bsr_block"`. (Catch-all: a 200 page without a rank block is
    either an unrecognized CAPTCHA, a deleted listing, or a layout we don't
    handle — all three should be treated as failures, not silently parsed.)
  - Any other non-200 → `http_error` with the status code.
  - Exceptions from `requests` (connection errors, timeouts) → `timeout` with
    the exception class name in `reason_detail`.
- The fetch function does **not** retry internally. Retries are orchestrated
  one level up (see `scrape.py`).

## Parsing: `src/parse.py`

Public function: `parse_product_page(html: str, asin: str) -> ParsedPage`

Where `ParsedPage` is a dataclass with:
- `asin: str`
- `title: str | None`
- `author: str | None`
- `ranks: list[RankEntry]`  # always includes overall + sub-categories

And `RankEntry` is:
- `category_id: str`        # 'books' for overall, else numeric string
- `category_name: str`
- `rank: int`

### Requirements

- Use BeautifulSoup with the stdlib `html.parser` (no `lxml` dependency
  required).
- **Reference implementation:** the PoC parser (`poc_parser.py`, provided
  alongside this plan in the project root) already extracts the right values
  from `fixtures/jfk.html`. Port its logic into `parse.py`, refactoring to
  return the dataclasses above instead of printing JSON. Do not redesign the
  parsing approach from scratch — the PoC's strategy (find the `<li>` whose
  text starts with "Best Sellers Rank", split header text from nested
  `ul.zg_hrsr`, pull category IDs from href patterns) is known-good. After
  porting, `poc_parser.py` can stay in the repo as historical reference; do
  not import from it.
- Store overall rank with `category_id = 'books'` and `category_name = 'Books'`.
- Raise `ParseError` (a custom exception defined in `parse.py`) if no rank
  block is found. The fetcher should have caught this already as a CAPTCHA,
  so reaching the parser without a rank block indicates a logic bug — fail
  loudly.
- It is acceptable for a book to have zero sub-categories (rare but possible).
  It is NOT acceptable for a book to have zero ranks total — that's a parse
  error.

## Orchestration: `src/scrape.py`

CLI entry point. Run with `python -m src.scrape [options]`.

### Default behavior (no flags)

1. Set up a log file at `logs/run-YYYY-MM-DD.log` (append mode). See "Logging"
   below.
2. Load `books.json`, filter to `active: true`.
3. Shuffle the book order (so a partial run doesn't always cover the same
   prefix).
4. Create one `requests.Session()` for the whole run.
5. For each book, in sequence (not parallel):
   - Fetch the page.
   - If fetch succeeds, parse it. Insert rows into `snapshots` with
     `INSERT OR IGNORE`. Log success with rank counts. If the book's
     `books.json` title was empty, append to `discovered_titles.txt`.
   - If fetch fails, insert a row into `failures`. Log failure with reason.
   - Sleep a random interval between 45 and 90 seconds before the next book.
6. After the first pass completes, build a list of ASINs that failed this run.
7. If any failures (and `--no-retry` not set), wait 15 minutes, then retry
   those once. Same insert logic.
8. Print a summary to stdout: `N books, M succeeded, K still failing after
   retry`.

### Flags

- `--dry-run` — do everything except write to the database. Useful for sanity
  checks. Still writes the log file.
- `--asin ASIN` — only scrape one specific ASIN. Useful for debugging.
- `--no-retry` — skip the 15-minute retry pass.
- `--db PATH` — override database path (default `bsr.db`).

### Re-parsing from disk: `src/reparse.py`

Separate CLI entry, run with `python -m src.reparse <html_file_or_directory>`.

- For a file: parse it, print the result as JSON to stdout, do not touch the
  db.
- For a directory: parse every `.html` file in it, print one JSON object per
  file.

This lets me develop and test the parser against saved pages without hitting
the network.

## Logging

- Use Python's `logging` module.
- Format: `%(asctime)s %(levelname)s %(message)s`
- Level: `INFO` by default. Use `WARNING` for individual book failures, `INFO`
  for successes and lifecycle events (run start/end, retry pass start), `ERROR`
  for things that should never happen (e.g. parse error after the fetcher
  said the page was OK).
- Log to both the log file and stdout (use two handlers on the root logger).
- Do not log full HTML bodies. Log ASIN, status, reason, rank counts — that's
  it.

## Politeness and rate limiting

- Random 45–90 sec gap between requests. At 35 books, that's a ~30–50 minute
  run. At 100 books it'll be ~75–150 minutes. Fine.
- One sequential request at a time. No threading, no asyncio.
- Run once per day. Pick a time (I'll handle scheduling — cron/launchd, not in
  scope for this plan).
- The User-Agent should look like a normal Chrome browser. Do not put my email
  or "bot" in the UA, that just gets blocked faster.

## What "success" means (the most important section)

The single biggest failure mode I'm worried about is the scraper writing
**wrong data** to the database — parsing a CAPTCHA page or an error page as if
it were a real product page and silently inserting nulls or zeros. The
database is the permanent record; bad data in it is much worse than missing
data.

Therefore, the rule everywhere in the code is:

> **If we cannot positively confirm the page is a real product page with a
> real BSR block, treat it as a failure and write to `failures`, never to
> `snapshots`.**

Concretely:
- 200 status with no "Best Sellers Rank" string anywhere → failure.
- A book that briefly has no rank (e.g. brand new release) → failure for
  today, recover tomorrow.
- A parse exception of any kind → failure, do not insert a partial row.

Missing days are fine. Wrong rows are not.

## Testing requirements

- `tests/test_parse.py`:
  - Parse `fixtures/jfk.html` and assert the exact rank values:
    - overall = 857576, category_id = `'books'`, category_name = `'Books'`
    - sub-rank 698 in category_id `'16023131'` ("United States Executive Government")
    - sub-rank 859 in category_id `'9681307011'` ("US Presidents")
    - sub-rank 14187 in category_id `'4853'` ("United States History (Books)")
    - title = "The Life of John Kennedy (Presidential Chronicles - Individual)"
    - author = "David Fisher"
  - Add a placeholder test for "fixture with no sub-ranks" marked with
    `pytest.skip("fixture not yet collected")`.
  - Add a placeholder test for "CAPTCHA page raises ParseError" marked with
    `pytest.skip("fixture not yet collected")`.
- `tests/test_db.py`:
  - Creating the schema is idempotent.
  - Inserting the same (asin, capture_date, category_id) twice results in one
    row (UNIQUE constraint).
  - Querying snapshots for a given ASIN returns them in date order.

Tests must pass with `pytest` from the project root.

## README requirements

A README.md with:
- One-paragraph description of what this does
- Install instructions (Python 3.11+, `pip install -r requirements.txt`)
- How to run a one-off fetch: `python -m src.scrape`
- How to run in dry-run mode
- How to debug one book: `python -m src.scrape --asin B0GY7T45YS`
- How to re-parse a saved HTML file: `python -m src.reparse path/to/file.html`
- How to add a new book (edit `books.json`)
- How to back up the database (just `cp bsr.db bsr.db.backup-YYYY-MM-DD`)
- How to inspect the database (recommend DB Browser for SQLite, link to
  https://sqlitebrowser.org/)
- Where logs live and how to read them
- Where `discovered_titles.txt` comes from and what to do with it
- A "Known limitations" section that lists: CAPTCHA-induced gaps are expected;
  the parser depends on Amazon's HTML and may need updates if they redesign;
  no cloud deployment is included yet; UTC date boundary means late-night runs
  near midnight UTC could occasionally land on the "wrong" day.

## Order of work for the implementing agent

Build in this order, validate each before moving on:

1. `src/parse.py` + `tests/test_parse.py` against the JFK fixture. The PoC
   already proved this works; the goal is just to productionize it. Don't move
   on until tests pass.
2. `src/db.py` + `tests/test_db.py`. Schema, inserts, dedupe.
3. `src/reparse.py`. So I can sanity-check the parser on more pages before any
   network calls.
4. `src/fetch.py`. Include CAPTCHA detection from day one — do not add it
   later.
5. `src/scrape.py`. Orchestration on top of the pieces above.
6. README.

Do not add features beyond this plan. If something is ambiguous, prefer the
simpler interpretation and note it in the README's "Known limitations" section.
