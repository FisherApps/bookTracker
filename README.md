# Amazon BSR Tracker

Tracks Amazon Best Sellers Rank (BSR) over time for a curated list of books. One snapshot per book per day, stored in a local SQLite database for later visualization.

## Install

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Run a full fetch

```bash
python -m src.scrape
```

This loads `books.json`, fetches each active book's product page, parses BSR data, and stores it in `bsr.db`. Books are processed sequentially with a 45–90 second random delay between requests.

### Dry-run mode

Fetches and parses but does not write to the database:

```bash
python -m src.scrape --dry-run
```

### Debug one book

```bash
python -m src.scrape --asin B0GY7T45YS
```

### Skip the retry pass

```bash
python -m src.scrape --no-retry
```

### Re-parse saved HTML

Parse a single file or all `.html` files in a directory (no network, no DB writes):

```bash
python -m src.reparse path/to/file.html
python -m src.reparse path/to/directory/
```

## Adding a new book

Edit `books.json` and add an entry:

```json
{
  "asin": "B0XXXXXXXXX",
  "title": "",
  "active": true,
  "notes": ""
}
```

The `asin` field is required. Set `active` to `false` to skip a book without removing it.

## Backing up the database

```bash
cp bsr.db bsr.db.backup-$(date +%Y-%m-%d)
```

## Inspecting the database

[DB Browser for SQLite](https://sqlitebrowser.org/) is recommended. Open `bsr.db` directly.

## Logs

Each run appends to `logs/run-YYYY-MM-DD.log`. Logs include per-book success/failure status and rank counts. Full HTML is never logged.

## Discovered titles

When a book with an empty `title` in `books.json` is successfully fetched, its discovered title is appended to `discovered_titles.txt`. You can paste these back into `books.json` at your convenience. The file is append-only and never modifies `books.json` directly.

## Known limitations

- **CAPTCHA-induced gaps are expected.** Amazon may challenge requests at any time. Missing days are accepted; wrong data is not.
- **The parser depends on Amazon's current HTML structure.** If Amazon redesigns product pages, `src/parse.py` will need updates.
- **No cloud deployment is included.** Scheduling (cron/launchd) is left to the user.
- **UTC date boundary.** `capture_date` is UTC. A late-night run near midnight UTC could occasionally land on the "wrong" calendar day relative to your local time zone.
