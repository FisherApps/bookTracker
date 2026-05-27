"""Orchestrates fetch + parse + write for all active books.

Usage:
    python -m src.scrape [--dry-run] [--asin ASIN] [--no-retry] [--db PATH]
"""

import argparse
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.db import get_connection, insert_failure, insert_snapshot
from src.fetch import FetchResult, fetch_product_html
from src.parse import ParseError, parse_product_page

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOOKS_FILE = PROJECT_ROOT / "books.json"
DISCOVERED_TITLES_FILE = PROJECT_ROOT / "discovered_titles.txt"
LOGS_DIR = PROJECT_ROOT / "logs"


def setup_logging() -> None:
    """Configure logging to file and stdout."""
    LOGS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"run-{today}.log"

    fmt = "%(asctime)s %(levelname)s %(message)s"
    handlers = [
        logging.FileHandler(log_file, mode="a"),
        logging.StreamHandler(),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def load_active_books() -> list[dict]:
    """Load books.json and return only active entries."""
    with open(BOOKS_FILE) as f:
        books = json.load(f)
    return [b for b in books if b.get("active", True)]


def load_discovered_asins() -> set[str]:
    """Load the set of ASINs already in discovered_titles.txt."""
    if not DISCOVERED_TITLES_FILE.exists():
        return set()
    asins = set()
    for line in DISCOVERED_TITLES_FILE.read_text().splitlines():
        parts = line.split(None, 1)
        if parts:
            asins.add(parts[0])
    return asins


def append_discovered_title(asin: str, title: str, discovered: set[str]) -> None:
    """Append a discovered title if not already known."""
    if asin in discovered:
        return
    with open(DISCOVERED_TITLES_FILE, "a") as f:
        f.write(f"{asin}  {title}\n")
    discovered.add(asin)


def process_book(
    book: dict,
    session: requests.Session,
    conn,
    now: datetime,
    dry_run: bool,
    discovered: set[str],
) -> bool:
    """Fetch, parse, and store data for one book. Returns True on success."""
    asin = book["asin"]
    result: FetchResult = fetch_product_html(asin, session)

    if result.status != "ok":
        logging.warning("FETCH FAILED %s — %s (%s)", asin, result.status, result.reason_detail)
        if not dry_run:
            insert_failure(
                conn,
                asin=asin,
                attempted_at=now.isoformat(timespec="seconds"),
                reason=result.status,
                http_status=result.http_status,
                detail=result.reason_detail,
            )
        return False

    # Parse
    try:
        parsed = parse_product_page(result.html, asin)
    except ParseError as e:
        logging.error("PARSE ERROR %s — %s", asin, e)
        if not dry_run:
            insert_failure(
                conn,
                asin=asin,
                attempted_at=now.isoformat(timespec="seconds"),
                reason="parse_error",
                detail=str(e),
            )
        return False

    # Insert snapshots
    capture_date = now.strftime("%Y-%m-%d")
    captured_at = now.isoformat(timespec="seconds")
    for rank_entry in parsed.ranks:
        if not dry_run:
            insert_snapshot(
                conn,
                asin=asin,
                captured_at=captured_at,
                capture_date=capture_date,
                category_id=rank_entry.category_id,
                category_name=rank_entry.category_name,
                rank=rank_entry.rank,
            )

    logging.info(
        "OK %s — %d ranks stored%s",
        asin,
        len(parsed.ranks),
        " (dry-run)" if dry_run else "",
    )

    # Title discovery (store format too)
    book_title = book.get("title", "")
    if not book_title and parsed.title:
        discovered_title = parsed.title
        if parsed.book_format:
            discovered_title += f"\t{parsed.book_format}"
        append_discovered_title(asin, discovered_title, discovered)

    return True


def run_pass(
    books: list[dict],
    session: requests.Session,
    conn,
    dry_run: bool,
    discovered: set[str],
) -> list[dict]:
    """Run one pass over books. Returns list of books that failed."""
    failed = []
    for i, book in enumerate(books):
        now = datetime.now(timezone.utc)
        success = process_book(book, session, conn, now, dry_run, discovered)
        if not success:
            failed.append(book)
        # Sleep between requests (not after the last one)
        if i < len(books) - 1:
            delay = random.uniform(45, 75)
            logging.info("Sleeping %.0f seconds...", delay)
            time.sleep(delay)
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch BSR data for tracked books")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse but don't write to DB")
    parser.add_argument("--asin", type=str, help="Only scrape one specific ASIN")
    parser.add_argument("--no-retry", action="store_true", help="Skip the retry pass")
    parser.add_argument("--db", type=str, default=str(PROJECT_ROOT / "bsr.db"), help="Database path")
    args = parser.parse_args()

    setup_logging()
    logging.info("=== BSR Tracker run started ===")

    books = load_active_books()
    if args.asin:
        books = [b for b in books if b["asin"] == args.asin]
        if not books:
            logging.error("ASIN %s not found in books.json", args.asin)
            return

    random.shuffle(books)
    logging.info("Tracking %d books", len(books))

    conn = None if args.dry_run else get_connection(args.db)
    session = requests.Session()
    discovered = load_discovered_asins()

    # First pass
    failed = run_pass(books, session, conn, args.dry_run, discovered)

    # Retry pass
    if failed and not args.no_retry and not args.dry_run:
        logging.info("Retry pass: %d books failed, waiting 15 minutes...", len(failed))
        time.sleep(15 * 60)
        random.shuffle(failed)
        failed = run_pass(failed, session, conn, args.dry_run, discovered)

    # Summary
    succeeded = len(books) - len(failed)
    summary = f"{len(books)} books, {succeeded} succeeded, {len(failed)} failed"
    logging.info("=== Run complete: %s ===", summary)
    print(summary)

    if conn:
        conn.close()


if __name__ == "__main__":
    main()
