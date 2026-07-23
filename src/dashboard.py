"""Generate a static dashboard HTML file from the BSR database.

Usage:
    python -m src.dashboard [--db PATH] [--out PATH]
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "bsr.db"
DEFAULT_OUT = PROJECT_ROOT / "dashboard.html"


def _infer_format_from_title(raw_title: str) -> str | None:
    """Infer Kindle vs Hardcover vs Paperback from title pattern.

    Kindle titles contain "Book N" in parentheses, e.g. "(Presidential Chronicles - Individual Book 34)".
    Hardcover titles have the same parenthetical but without "Book N", e.g. "(Presidential Chronicles - Individual)".
    Volume/collection titles with "Book N" in parens → Kindle.
    Volume/collection titles with NO parenthetical → Paperback.
    """
    import re
    paren = re.search(r"\(([^)]*)\)", raw_title)
    if not paren:
        # Volume titles without parenthetical are paperbacks
        if "Presidential Chronicles" in raw_title:
            return "Paperback"
        return None
    inner = paren.group(1)
    if re.search(r"\bBook\s+\d+", inner):
        return "Kindle"
    if "Presidential Chronicles" in inner:
        return "Hardcover"
    return None


def _format_display_title(raw_title: str, book_format: str | None) -> str:
    """Strip parenthetical content from title, append format for Kindle/Hardcover."""
    import re
    # Infer format from title pattern if not explicitly provided
    if not book_format:
        book_format = _infer_format_from_title(raw_title)
    # Strip everything in parentheses
    title = re.sub(r"\s*\([^)]*\)", "", raw_title).strip()
    # Append format suffix
    if book_format:
        title += f" - {book_format}"
    return title


def load_books_json() -> dict[str, str]:
    """Load books.json and return {asin: display_title} mapping, with discovered_titles.txt as fallback."""
    books_file = PROJECT_ROOT / "books.json"
    with open(books_file) as f:
        books = json.load(f)
    titles = {b["asin"]: b.get("title", "") for b in books}

    # Fill in blanks from discovered_titles.txt (format: "ASIN  title\tFormat" or "ASIN  title")
    discovered_file = PROJECT_ROOT / "discovered_titles.txt"
    formats: dict[str, str | None] = {}
    if discovered_file.exists():
        for line in discovered_file.read_text().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                asin = parts[0]
                title_and_format = parts[1]
                # Check for tab-separated format
                if "\t" in title_and_format:
                    raw_title, fmt = title_and_format.rsplit("\t", 1)
                    formats[asin] = fmt.strip()
                else:
                    raw_title = title_and_format
                    formats[asin] = None
                if not titles.get(asin):
                    titles[asin] = raw_title.strip()

    # Apply display formatting
    display_titles = {}
    for asin, title in titles.items():
        if title:
            display_titles[asin] = _format_display_title(title, formats.get(asin))
        else:
            display_titles[asin] = ""
    return display_titles


def query_all_data(db_path: Path) -> dict:
    """Query the database and return structured data for the dashboard."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get all snapshots ordered by date
    rows = conn.execute(
        "SELECT asin, capture_date, category_id, category_name, rank "
        "FROM snapshots ORDER BY capture_date"
    ).fetchall()

    # Get latest date
    latest = conn.execute("SELECT MAX(capture_date) FROM snapshots").fetchone()[0]

    # Get failure counts by date
    failures = conn.execute(
        "SELECT DATE(attempted_at) as d, COUNT(*) as c FROM failures GROUP BY d ORDER BY d"
    ).fetchall()

    conn.close()

    # Organize by ASIN
    books: dict[str, dict] = {}
    all_dates: set[str] = set()

    for row in rows:
        asin = row["asin"]
        date = row["capture_date"]
        all_dates.add(date)

        if asin not in books:
            books[asin] = {"overall": {}, "subcategories": {}}

        if row["category_id"] == "books":
            books[asin]["overall"][date] = row["rank"]
        else:
            cat_id = row["category_id"]
            if cat_id not in books[asin]["subcategories"]:
                books[asin]["subcategories"][cat_id] = {
                    "name": row["category_name"],
                    "data": {},
                }
            books[asin]["subcategories"][cat_id]["data"][date] = row["rank"]

    # Latest overall ranks for summary table
    latest_ranks = []
    for asin, data in books.items():
        if latest and latest in data["overall"]:
            latest_ranks.append({
                "asin": asin,
                "rank": data["overall"][latest],
                "date": latest,
            })

    latest_ranks.sort(key=lambda x: x["rank"])

    return {
        "books": books,
        "dates": sorted(all_dates),
        "latest_date": latest,
        "latest_ranks": latest_ranks,
        "failure_counts": {row["d"]: row["c"] for row in failures},
        "total_snapshots": len(rows),
    }


def generate_html(data: dict, book_titles: dict[str, str]) -> str:
    """Generate the dashboard HTML."""
    # Build display names
    display_names = {}
    for asin in data["books"]:
        title = book_titles.get(asin, "")
        display_names[asin] = title if title else asin

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # Prepare chart data for JS
    chart_data = {
        "dates": data["dates"],
        "books": {},
    }
    for asin, book_data in data["books"].items():
        chart_data["books"][asin] = {
            "name": display_names[asin],
            "overall": book_data["overall"],
            "subcategories": {
                cat_id: {"name": cat["name"], "data": cat["data"]}
                for cat_id, cat in book_data["subcategories"].items()
            },
        }

    # Summary stats
    num_books = len(data["books"])
    num_days = len(data["dates"])

    # Best rank
    best_rank_book = ""
    best_rank_val = None
    for item in data["latest_ranks"]:
        if best_rank_val is None or item["rank"] < best_rank_val:
            best_rank_val = item["rank"]
            best_rank_book = display_names.get(item["asin"], item["asin"])

    # Latest run info
    latest_date = data["dates"][-1] if data["dates"] else ""
    latest_date_fmt = ""
    if latest_date:
        from datetime import datetime as _dt
        latest_date_fmt = _dt.strptime(latest_date, "%Y-%m-%d").strftime("%b %-d")
    latest_fetched = len(data["latest_ranks"])

    # Top 5 ASINs by best rank for the overview chart
    top5 = [item["asin"] for item in data["latest_ranks"][:5]]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Presidential Chronicles — Sales Rank Tracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@300;400;500;600;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

:root {{
    --bg: #faf8f5;
    --bg-card: #ffffff;
    --bg-hover: #f5f2ee;
    --border: #e8e3dc;
    --border-light: #f0ece6;
    --text: #2c2416;
    --text-secondary: #7a6f60;
    --text-muted: #a89f92;
    --accent: #b8860b;
    --accent-light: #daa520;
    --accent-subtle: #f5e6c8;
    --success: #4a7c59;
    --kindle: #e67e22;
    --hardcover: #2c6fbb;
    --paperback: #7a6f60;
    --shadow: 0 1px 3px rgba(44, 36, 22, 0.06), 0 4px 12px rgba(44, 36, 22, 0.04);
    --shadow-lg: 0 4px 12px rgba(44, 36, 22, 0.08), 0 12px 36px rgba(44, 36, 22, 0.06);
    --radius: 10px;
    --font-display: 'Crimson Pro', Georgia, serif;
    --font-body: 'DM Sans', -apple-system, sans-serif;
}}

body {{
    font-family: var(--font-body);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    line-height: 1.5;
}}

.container {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 48px 32px;
}}

/* Header */
header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    margin-bottom: 40px;
    padding-bottom: 28px;
    border-bottom: 1px solid var(--border);
}}

header .left h1 {{
    font-family: var(--font-display);
    font-size: 2.5rem;
    font-weight: 300;
    letter-spacing: -0.02em;
    color: var(--text);
    margin-bottom: 4px;
}}

header .left .meta {{
    font-size: 0.85rem;
    color: var(--text-muted);
    letter-spacing: 0.02em;
}}

/* Time range controls */
.time-range {{
    display: flex;
    gap: 2px;
    background: var(--border-light);
    border-radius: 8px;
    padding: 3px;
}}

.time-btn {{
    padding: 7px 14px;
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-secondary);
    border: none;
    background: none;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
    letter-spacing: 0.02em;
}}

.time-btn:hover {{
    color: var(--text);
    background: rgba(255,255,255,0.5);
}}

.time-btn.active {{
    background: var(--bg-card);
    color: var(--text);
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}

/* Stat Cards */
.stats {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    margin-bottom: 40px;
}}

.stat {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 22px 24px;
    box-shadow: var(--shadow);
}}

.stat .label {{
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 8px;
    font-weight: 500;
}}

.stat .value {{
    font-family: var(--font-display);
    font-size: 2rem;
    font-weight: 600;
    color: var(--accent);
}}

.stat .detail {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-top: 4px;
}}

/* Overview Chart Section */
.overview-chart {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 28px;
    margin-bottom: 40px;
}}

.overview-chart .section-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}}

.overview-chart h2 {{
    font-family: var(--font-display);
    font-size: 1.3rem;
    font-weight: 500;
}}

.overview-chart .chart-hint {{
    font-size: 0.75rem;
    color: var(--text-muted);
}}

.chart-wrapper {{
    position: relative;
    height: 280px;
}}

.chart-wrapper.tall {{
    height: 320px;
}}

/* Filter Tabs */
.controls-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}}

.tabs {{
    display: flex;
    gap: 2px;
    background: var(--border-light);
    border-radius: 8px;
    padding: 3px;
    width: fit-content;
}}

.tab {{
    padding: 8px 18px;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--text-secondary);
    border: none;
    background: none;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
    letter-spacing: 0.01em;
}}

.tab:hover {{
    color: var(--text);
    background: rgba(255,255,255,0.5);
}}

.tab.active {{
    background: var(--bg-card);
    color: var(--text);
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}

/* Book List */
.book-list {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
}}

.book-list-header {{
    display: grid;
    grid-template-columns: 36px 1fr auto minmax(100px, 150px) 28px;
    gap: 14px;
    padding: 10px 24px;
    border-bottom: 2px solid var(--border);
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
}}

.book-row {{
    display: grid;
    grid-template-columns: 36px 1fr auto minmax(100px, 150px) 28px;
    gap: 14px;
    align-items: center;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border-light);
    cursor: pointer;
    transition: background 0.15s;
}}

.book-row:last-child {{
    border-bottom: none;
}}

.book-row:hover {{
    background: var(--bg-hover);
}}

.book-row.selected {{
    background: var(--accent-subtle);
    border-bottom-color: var(--accent-subtle);
}}

.book-row .position {{
    font-family: var(--font-display);
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-muted);
    text-align: center;
}}

.book-row .position.top3 {{
    color: var(--accent);
}}

.book-row .info {{
    min-width: 0;
}}

.book-row .title {{
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--text);
    line-height: 1.4;
}}

.book-row .format-badge {{
    display: inline-block;
    font-size: 0.6rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 8px;
    vertical-align: middle;
}}

.badge-kindle {{ background: #fef3e6; color: var(--kindle); }}
.badge-hardcover {{ background: #eaf2fb; color: var(--hardcover); }}
.badge-paperback {{ background: #f3f1ee; color: var(--paperback); }}

/* Top-25 "hot" indicator */
.hot-dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #e53935;
    margin-left: 8px;
    vertical-align: middle;
    box-shadow: 0 0 0 0 rgba(229, 57, 53, 0.6);
    animation: hotPulse 1.2s infinite;
}}

@keyframes hotPulse {{
    0%   {{ box-shadow: 0 0 0 0 rgba(229, 57, 53, 0.6); opacity: 1; }}
    70%  {{ box-shadow: 0 0 0 6px rgba(229, 57, 53, 0); opacity: 0.5; }}
    100% {{ box-shadow: 0 0 0 0 rgba(229, 57, 53, 0); opacity: 1; }}
}}

.book-row .rank-display {{
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
}}

/* Top subcategory column */
.book-row .top-cat {{
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
}}

.book-row .top-cat-name {{
    font-size: 0.78rem;
    color: var(--text-secondary);
    line-height: 1.25;
    /* Prefer wrapping the category name (up to 2 lines) rather than the title */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
}}

.book-row .top-cat-rank {{
    font-family: var(--font-display);
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--accent);
}}

.book-row .top-cat-empty {{
    color: var(--text-muted);
    font-size: 0.9rem;
}}

.book-row .expand-icon {{
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
}}

.book-row .expand-icon svg {{
    width: 14px;
    height: 14px;
    transition: transform 0.25s ease;
    fill: none;
    stroke: var(--text-muted);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}}

.book-row.selected .expand-icon svg {{
    transform: rotate(180deg);
    stroke: var(--accent);
}}

/* Inline Detail */
.book-detail {{
    padding: 24px 28px 28px;
    background: var(--bg);
    border-bottom: 1px solid var(--border-light);
    animation: expandIn 0.25s ease;
}}

@keyframes expandIn {{
    from {{ opacity: 0; max-height: 0; padding-top: 0; padding-bottom: 0; }}
    to {{ opacity: 1; max-height: 800px; }}
}}

.book-detail .detail-stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}}

.book-detail .detail-stat {{
    text-align: center;
    padding: 14px 12px;
    background: var(--bg-card);
    border-radius: 8px;
    border: 1px solid var(--border-light);
}}

.book-detail .detail-stat .label {{
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 4px;
    font-weight: 500;
}}

.book-detail .detail-stat .value {{
    font-family: var(--font-display);
    font-size: 1.3rem;
    font-weight: 600;
    color: var(--text);
}}

.chart-label {{
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    font-weight: 500;
    margin-bottom: 10px;
    margin-top: 20px;
}}

/* President Filter */
.president-filter {{
    position: relative;
}}

.president-btn {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    font-size: 0.85rem;
    font-family: var(--font-body);
    font-weight: 500;
    color: var(--text);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    box-shadow: var(--shadow);
}}

.president-btn:hover {{
    border-color: var(--accent);
}}

.president-btn svg {{
    fill: none;
    stroke: var(--text-muted);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: transform 0.2s;
}}

.president-btn.open svg {{
    transform: rotate(180deg);
}}

.president-dropdown {{
    display: none;
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    width: 260px;
    max-height: 340px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    z-index: 100;
    overflow: hidden;
}}

.president-dropdown.open {{
    display: block;
}}

.president-dropdown input {{
    width: 100%;
    padding: 10px 14px;
    font-size: 0.85rem;
    font-family: var(--font-body);
    border: none;
    border-bottom: 1px solid var(--border-light);
    background: transparent;
    color: var(--text);
    outline: none;
    box-sizing: border-box;
}}

.president-dropdown input::placeholder {{
    color: var(--text-muted);
}}

.president-list {{
    max-height: 270px;
    overflow-y: auto;
}}

.president-option {{
    padding: 9px 14px;
    font-size: 0.85rem;
    color: var(--text);
    cursor: pointer;
    transition: background 0.15s;
}}

.president-option:hover {{
    background: var(--bg-hover);
}}

.president-option.active {{
    color: var(--accent);
    font-weight: 600;
}}

/* Search */
.search-box {{
    margin-bottom: 16px;
}}

.search-box input {{
    width: 100%;
    padding: 12px 16px;
    font-size: 0.9rem;
    font-family: var(--font-body);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    outline: none;
    transition: border-color 0.2s;
    box-shadow: var(--shadow);
}}

.search-box input:focus {{
    border-color: var(--accent);
}}

.search-box input::placeholder {{
    color: var(--text-muted);
}}

/* Custom date range */
.date-range {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: 16px;
    padding-left: 16px;
    border-left: 1px solid var(--border);
}}

.date-range input {{
    padding: 6px 10px;
    font-size: 0.75rem;
    font-family: var(--font-body);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    outline: none;
}}

.date-range input:focus {{
    border-color: var(--accent);
}}

.date-range label {{
    font-size: 0.7rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}

/* Export */
.export-btn {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    font-size: 0.85rem;
    font-family: var(--font-body);
    font-weight: 500;
    color: var(--text);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    box-shadow: var(--shadow);
    white-space: nowrap;
}}

.export-btn:hover {{
    border-color: var(--accent);
    color: var(--accent);
}}

.export-btn svg {{
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}}

/* Responsive */
@media (max-width: 768px) {{
    .container {{ padding: 24px 16px; }}
    header {{ flex-direction: column; align-items: flex-start; gap: 16px; }}
    header .left h1 {{ font-size: 1.8rem; }}
    .stats {{ grid-template-columns: 1fr; }}
    .book-list-header {{ grid-template-columns: 28px 1fr auto 20px; }}
    .book-row {{ grid-template-columns: 28px 1fr auto 20px; padding: 12px 16px; }}
    .top-cat, .top-cat-header {{ display: none; }}
    .controls-row {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
}}
</style>
</head>
<body>

<div class="container">

<header>
    <div class="left">
        <h1>Presidential Chronicles</h1>
        <div class="meta">Sales Rank Tracker &middot; Updated {generated_at}</div>
    </div>
    <div style="display:flex;align-items:center;gap:12px;">
        <div class="time-range" id="timeRange">
            <button class="time-btn" data-days="7">7d</button>
            <button class="time-btn" data-days="30">30d</button>
            <button class="time-btn" data-days="90">90d</button>
            <button class="time-btn active" data-days="0">All</button>
        </div>
        <div class="date-range">
            <label>From</label>
            <input type="date" id="dateFrom">
            <label>To</label>
            <input type="date" id="dateTo">
        </div>
        <button class="export-btn" id="exportBtn">
            <svg viewBox="0 0 24 24" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Export CSV
        </button>
    </div>
</header>

<div class="stats">
    <div class="stat">
        <div class="label">Books Tracked</div>
        <div class="value">{num_books}</div>
        <div class="detail">{num_days} day{"s" if num_days != 1 else ""} of data collected</div>
    </div>
    <div class="stat">
        <div class="label">Best Overall Rank</div>
        <div class="value">{f"#{best_rank_val:,}" if best_rank_val else "—"}</div>
        <div class="detail">{best_rank_book}</div>
    </div>
    <div class="stat">
        <div class="label">Latest Run</div>
        <div class="value">{latest_date_fmt or "—"}</div>
        <div class="detail">{latest_fetched}/{num_books} books fetched</div>
    </div>
</div>

<div class="overview-chart">
    <div class="section-header">
        <h2>Top Performers Over Time</h2>
        <span class="chart-hint">Best 5 books by current rank</span>
    </div>
    <div class="chart-wrapper tall">
        <canvas id="overviewChart"></canvas>
    </div>
</div>

<div class="controls-row">
    <div class="tabs" id="formatTabs">
        <button class="tab active" data-filter="all">All</button>
        <button class="tab" data-filter="kindle">Kindle</button>
        <button class="tab" data-filter="hardcover">Hardcover</button>
        <button class="tab" data-filter="paperback">Paperback</button>
    </div>
    <div class="president-filter">
        <button class="president-btn" id="presidentBtn">
            <span id="presidentLabel">All Presidents</span>
            <svg viewBox="0 0 24 24" width="14" height="14"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </button>
        <div class="president-dropdown" id="presidentDropdown">
            <input type="text" id="presidentSearch" placeholder="Search presidents...">
            <div class="president-list" id="presidentList"></div>
        </div>
    </div>
</div>

<div class="search-box">
    <input type="text" id="searchInput" placeholder="Search books by title...">
</div>

<div class="book-list">
    <div class="book-list-header">
        <div>#</div>
        <div>Title</div>
        <div id="rankHeader">Overall Rank</div>
        <div class="top-cat-header">Top Category</div>
        <div></div>
    </div>
    <div id="bookList"></div>
</div>

</div>

<script>
const DATA = {json.dumps(chart_data)};
const TOP5 = {json.dumps(top5)};

const PALETTE = {{
    overall: '#b8860b',
    top5: ['#b8860b', '#2c6fbb', '#4a7c59', '#9b59b6', '#e67e22'],
    cats: ['#2c6fbb', '#4a7c59', '#9b59b6', '#e67e22', '#16a085'],
    grid: '#f0ece6',
    text: '#7a6f60',
}};

// --- Utilities ---
function getFormat(name) {{
    if (name.includes('- Kindle')) return 'kindle';
    if (name.includes('- Hardcover')) return 'hardcover';
    if (name.includes('- Paperback')) return 'paperback';
    return 'all';
}}

function getFormatBadge(name) {{
    const fmt = getFormat(name);
    if (fmt === 'kindle') return '<span class="format-badge badge-kindle">Kindle</span>';
    if (fmt === 'hardcover') return '<span class="format-badge badge-hardcover">Hardcover</span>';
    if (fmt === 'paperback') return '<span class="format-badge badge-paperback">Paperback</span>';
    return '';
}}

function getCleanTitle(name) {{
    return name.replace(/\\s*-\\s*(Kindle|Hardcover|Paperback)$/, '');
}}

// True if any category ranking on the latest scrape is in the top 25
function isHot(asin) {{
    const book = DATA.books[asin];
    return Object.values(book.subcategories).some(cat => {{
        const r = cat.data[latestDate];
        return r !== undefined && r <= 25;
    }});
}}

// The subcategory where the book ranks best (lowest rank) on the latest scrape
function getTopSubcategory(asin) {{
    const book = DATA.books[asin];
    let bestRank = null;
    let bestName = '';
    Object.values(book.subcategories).forEach(cat => {{
        const r = cat.data[latestDate];
        if (r !== undefined && (bestRank === null || r < bestRank)) {{
            bestRank = r;
            bestName = cat.name;
        }}
    }});
    return bestRank === null ? null : {{ name: bestName, rank: bestRank }};
}}

// --- Time filtering ---
let timeRangeDays = 0; // 0 = all

function getFilteredDates() {{
    if (timeRangeDays === -1) {{
        const fromVal = document.getElementById('dateFrom').value;
        const toVal = document.getElementById('dateTo').value;
        return DATA.dates.filter(d => {{
            if (fromVal && d < fromVal) return false;
            if (toVal && d > toVal) return false;
            return true;
        }});
    }}
    if (timeRangeDays === 0) return DATA.dates;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - timeRangeDays);
    const cutoffStr = cutoff.toISOString().split('T')[0];
    return DATA.dates.filter(d => d >= cutoffStr);
}}

// --- Sort books ---
const asins = Object.keys(DATA.books);
const latestDate = DATA.dates[DATA.dates.length - 1];
asins.sort((a, b) => {{
    const ra = DATA.books[a].overall[latestDate] || Infinity;
    const rb = DATA.books[b].overall[latestDate] || Infinity;
    return ra - rb;
}});

let currentFilter = 'all';
let selectedAsin = null;

// --- Overview chart (top 5) ---
let overviewChart = null;

function renderOverviewChart() {{
    if (overviewChart) overviewChart.destroy();

    const dates = getFilteredDates();
    const datasets = [];

    TOP5.forEach((asin, i) => {{
        const book = DATA.books[asin];
        if (!book) return;
        const points = dates
            .filter(d => book.overall[d] !== undefined)
            .map(d => ({{ x: d, y: book.overall[d] }}));

        if (points.length > 0) {{
            datasets.push({{
                label: getCleanTitle(book.name),
                data: points,
                borderColor: PALETTE.top5[i],
                backgroundColor: PALETTE.top5[i] + '10',
                borderWidth: 2.5,
                pointRadius: points.length < 20 ? 5 : 3,
                pointBackgroundColor: PALETTE.top5[i],
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointHoverRadius: 8,
                tension: 0.3,
                fill: false,
            }});
        }}
    }});

    overviewChart = new Chart(document.getElementById('overviewChart'), {{
        type: 'line',
        data: {{ datasets }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'nearest', intersect: true }},
            scales: {{
                x: {{
                    type: 'category',
                    labels: dates,
                    ticks: {{ color: PALETTE.text, font: {{ size: 11 }}, maxRotation: 0, maxTicksLimit: 12 }},
                    grid: {{ color: PALETTE.grid }},
                }},
                y: {{
                    reverse: true,
                    ticks: {{
                        color: PALETTE.text,
                        font: {{ size: 11 }},
                        callback: v => '#' + v.toLocaleString(),
                    }},
                    grid: {{ color: PALETTE.grid }},
                    title: {{ display: true, text: 'Rank (lower = better)', color: PALETTE.text, font: {{ size: 11 }} }},
                }},
            }},
            plugins: {{
                legend: {{
                    position: 'bottom',
                    labels: {{
                        color: PALETTE.text,
                        font: {{ size: 11, family: "'DM Sans'" }},
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 20,
                    }},
                }},
                tooltip: {{
                    backgroundColor: '#2c2416',
                    titleFont: {{ family: "'DM Sans'" }},
                    bodyFont: {{ family: "'DM Sans'" }},
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {{
                        label: ctx => ` ${{ctx.dataset.label}}: #${{ctx.parsed.y.toLocaleString()}}`,
                    }},
                }},
            }},
        }},
    }});
}}

// --- Search ---
let searchQuery = '';
document.getElementById('searchInput').addEventListener('input', (e) => {{
    searchQuery = e.target.value.toLowerCase();
    renderBookList();
}});

// --- President filter ---
const PRESIDENTS = [
    'George Washington', 'John Adams', 'Thomas Jefferson', 'James Madison', 'James Monroe',
    'John Quincy Adams', 'Andrew Jackson', 'Martin Van Buren', 'William Henry Harrison', 'John Tyler',
    'James Polk', 'Zachary Taylor', 'Millard Fillmore', 'Franklin Pierce', 'James Buchanan',
    'Abraham Lincoln', 'Andrew Johnson', 'Ulysses Grant', 'Rutherford Hayes', 'James Garfield',
    'Chester Arthur', 'Grover Cleveland', 'Benjamin Harrison', 'William McKinley', 'Theodore Roosevelt',
    'William Taft', 'Woodrow Wilson', 'Warren Harding', 'Calvin Coolidge',
    'Herbert Hoover', 'Franklin Roosevelt', 'Harry Truman', 'Dwight Eisenhower',
    'John Kennedy', 'Lyndon Johnson', 'Richard Nixon', 'Gerald Ford',
];

let selectedPresident = '';
const presBtn = document.getElementById('presidentBtn');
const presDropdown = document.getElementById('presidentDropdown');
const presList = document.getElementById('presidentList');
const presSearch = document.getElementById('presidentSearch');
const presLabel = document.getElementById('presidentLabel');

function renderPresidentList(filter) {{
    presList.innerHTML = '';
    const allOpt = document.createElement('div');
    allOpt.className = 'president-option' + (!selectedPresident ? ' active' : '');
    allOpt.textContent = 'All Presidents';
    allOpt.addEventListener('click', () => selectPresident(''));
    presList.appendChild(allOpt);

    PRESIDENTS.forEach(name => {{
        if (filter && !name.toLowerCase().includes(filter)) return;
        const opt = document.createElement('div');
        opt.className = 'president-option' + (selectedPresident === name ? ' active' : '');
        opt.textContent = name;
        opt.addEventListener('click', () => selectPresident(name));
        presList.appendChild(opt);
    }});
}}

function selectPresident(name) {{
    selectedPresident = name;
    presLabel.textContent = name || 'All Presidents';
    presDropdown.classList.remove('open');
    presBtn.classList.remove('open');
    presSearch.value = '';
    selectedAsin = null;
    renderBookList();
}}

presBtn.addEventListener('click', (e) => {{
    e.stopPropagation();
    const isOpen = presDropdown.classList.toggle('open');
    presBtn.classList.toggle('open');
    if (isOpen) {{
        renderPresidentList('');
        setTimeout(() => presSearch.focus(), 10);
    }}
}});

presSearch.addEventListener('input', (e) => {{
    renderPresidentList(e.target.value.toLowerCase());
}});

presSearch.addEventListener('click', (e) => e.stopPropagation());

document.addEventListener('click', () => {{
    presDropdown.classList.remove('open');
    presBtn.classList.remove('open');
}});

presDropdown.addEventListener('click', (e) => e.stopPropagation());

// --- Custom date range ---
document.getElementById('dateFrom').addEventListener('change', applyCustomDateRange);
document.getElementById('dateTo').addEventListener('change', applyCustomDateRange);

function applyCustomDateRange() {{
    const fromVal = document.getElementById('dateFrom').value;
    const toVal = document.getElementById('dateTo').value;
    if (fromVal || toVal) {{
        timeRangeDays = -1;
        document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
    }}
    renderOverviewChart();
    if (selectedAsin) renderBookList();
}}

// --- Book list with inline expansion ---
function renderBookList() {{
    const container = document.getElementById('bookList');
    container.innerHTML = '';
    let position = 0;

    asins.forEach(asin => {{
        const book = DATA.books[asin];
        const fmt = getFormat(book.name);
        if (currentFilter !== 'all' && fmt !== currentFilter) return;
        if (searchQuery && !getCleanTitle(book.name).toLowerCase().includes(searchQuery)) return;
        if (selectedPresident && !book.name.toLowerCase().includes(selectedPresident.toLowerCase())) return;

        position++;
        const rank = book.overall[latestDate];
        const rankStr = rank ? '#' + rank.toLocaleString() : '—';
        const isSelected = asin === selectedAsin;

        const topCat = getTopSubcategory(asin);
        const topCatHtml = topCat
            ? `<div class="top-cat" title="${{topCat.name}}"><span class="top-cat-name">${{topCat.name}}</span><span class="top-cat-rank">#${{topCat.rank.toLocaleString()}}</span></div>`
            : '<div class="top-cat top-cat-empty">—</div>';

        const row = document.createElement('div');
        row.className = 'book-row' + (isSelected ? ' selected' : '');
        row.innerHTML = `
            <div class="position ${{position <= 3 ? 'top3' : ''}}">${{position}}</div>
            <div class="info">
                <div class="title">${{getCleanTitle(book.name)}}${{getFormatBadge(book.name)}}${{isHot(asin) ? '<span class="hot-dot" title="Top 25 in a category on the latest scrape"></span>' : ''}}</div>
            </div>
            <div class="rank-display">${{rankStr}}</div>
            ${{topCatHtml}}
            <div class="expand-icon"><svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"></polyline></svg></div>
        `;
        row.addEventListener('click', () => toggleBook(asin));
        container.appendChild(row);

        // Inline detail panel
        if (isSelected) {{
            const detail = document.createElement('div');
            detail.className = 'book-detail';
            detail.innerHTML = buildDetailHTML(asin);
            container.appendChild(detail);
            // Render charts after DOM insertion
            setTimeout(() => {{
                renderDetailCharts(asin);
            }}, 10);
        }}
    }});
}}

function toggleBook(asin) {{
    if (selectedAsin === asin) {{
        selectedAsin = null;
    }} else {{
        selectedAsin = asin;
    }}
    renderBookList();
}}

function buildDetailHTML(asin) {{
    const book = DATA.books[asin];
    const dates = getFilteredDates();
    const overallRank = book.overall[latestDate];
    const numDays = Object.keys(book.overall).length;
    const numCats = Object.keys(book.subcategories).length;

    let bestSub = null;
    let bestSubName = '';
    Object.values(book.subcategories).forEach(cat => {{
        const latestVal = cat.data[latestDate];
        if (latestVal && (!bestSub || latestVal < bestSub)) {{
            bestSub = latestVal;
            bestSubName = cat.name;
        }}
    }});

    let html = '<div class="detail-stats">';
    html += `<div class="detail-stat"><div class="label">Overall Rank</div><div class="value">${{overallRank ? '#' + overallRank.toLocaleString() : '—'}}</div></div>`;
    html += `<div class="detail-stat"><div class="label">Days Tracked</div><div class="value">${{numDays}}</div></div>`;
    html += `<div class="detail-stat"><div class="label">Categories</div><div class="value">${{numCats}}</div></div>`;
    if (bestSub) {{
        html += `<div class="detail-stat"><div class="label">Best Category</div><div class="value">#${{bestSub.toLocaleString()}}</div></div>`;
    }}
    html += '</div>';

    html += '<div class="chart-label">Overall Rank History</div>';
    html += '<div class="chart-wrapper"><canvas id="detailOverallChart"></canvas></div>';

    if (numCats > 0) {{
        html += '<div class="chart-label">Category Rankings</div>';
        html += '<div class="chart-wrapper"><canvas id="detailSubChart"></canvas></div>';
    }}

    return html;
}}

function renderDetailCharts(asin) {{
    const book = DATA.books[asin];
    const dates = getFilteredDates();

    // Overall chart
    const overallCanvas = document.getElementById('detailOverallChart');
    if (overallCanvas) {{
        const points = dates
            .filter(d => book.overall[d] !== undefined)
            .map(d => ({{ x: d, y: book.overall[d] }}));

        new Chart(overallCanvas, {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: 'Overall Rank',
                    data: points,
                    borderColor: PALETTE.overall,
                    backgroundColor: PALETTE.overall + '18',
                    borderWidth: 2.5,
                    pointRadius: points.length < 20 ? 5 : 3,
                    pointBackgroundColor: PALETTE.overall,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointHoverRadius: 7,
                    tension: 0.3,
                    fill: true,
                }}],
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'nearest', intersect: true }},
                scales: {{
                    x: {{
                        type: 'category',
                        labels: dates,
                        ticks: {{ color: PALETTE.text, font: {{ size: 11 }}, maxRotation: 0, maxTicksLimit: 12 }},
                        grid: {{ color: PALETTE.grid }},
                    }},
                    y: {{
                        reverse: true,
                        ticks: {{
                            color: PALETTE.text,
                            font: {{ size: 11 }},
                            callback: v => '#' + v.toLocaleString(),
                        }},
                        grid: {{ color: PALETTE.grid }},
                    }},
                }},
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        backgroundColor: '#2c2416',
                        padding: 12,
                        cornerRadius: 8,
                        callbacks: {{
                            label: ctx => `Rank: #${{ctx.parsed.y.toLocaleString()}}`,
                        }},
                    }},
                }},
            }},
        }});
    }}

    // Sub chart
    const subCanvas = document.getElementById('detailSubChart');
    if (subCanvas) {{
        const datasets = [];
        Object.entries(book.subcategories).forEach(([catId, cat], i) => {{
            const points = dates
                .filter(d => cat.data[d] !== undefined)
                .map(d => ({{ x: d, y: cat.data[d] }}));

            if (points.length > 0) {{
                datasets.push({{
                    label: cat.name,
                    data: points,
                    borderColor: PALETTE.cats[i % PALETTE.cats.length],
                    backgroundColor: PALETTE.cats[i % PALETTE.cats.length] + '12',
                    borderWidth: 2,
                    pointRadius: points.length < 20 ? 4 : 2.5,
                    pointBackgroundColor: PALETTE.cats[i % PALETTE.cats.length],
                    pointBorderColor: '#fff',
                    pointBorderWidth: 1.5,
                    pointHoverRadius: 6,
                    tension: 0.3,
                    fill: false,
                }});
            }}
        }});

        new Chart(subCanvas, {{
            type: 'line',
            data: {{ datasets }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'nearest', intersect: true }},
                scales: {{
                    x: {{
                        type: 'category',
                        labels: dates,
                        ticks: {{ color: PALETTE.text, font: {{ size: 11 }}, maxRotation: 0, maxTicksLimit: 12 }},
                        grid: {{ color: PALETTE.grid }},
                    }},
                    y: {{
                        reverse: true,
                        ticks: {{
                            color: PALETTE.text,
                            font: {{ size: 11 }},
                            callback: v => '#' + v.toLocaleString(),
                        }},
                        grid: {{ color: PALETTE.grid }},
                    }},
                }},
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{
                            color: PALETTE.text,
                            font: {{ size: 11, family: "'DM Sans'" }},
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 16,
                        }},
                    }},
                    tooltip: {{
                        backgroundColor: '#2c2416',
                        padding: 12,
                        cornerRadius: 8,
                        callbacks: {{
                            label: ctx => ` ${{ctx.dataset.label}}: #${{ctx.parsed.y.toLocaleString()}}`,
                        }},
                    }},
                }},
            }},
        }});
    }}
}}

// --- Time range buttons ---
document.querySelectorAll('.time-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        timeRangeDays = parseInt(btn.dataset.days);
        document.getElementById('dateFrom').value = '';
        document.getElementById('dateTo').value = '';
        renderOverviewChart();
        if (selectedAsin) renderBookList();
    }});
}});

// --- Format filter tabs ---
document.querySelectorAll('.tab').forEach(tab => {{
    tab.addEventListener('click', () => {{
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentFilter = tab.dataset.filter;
        selectedAsin = null;
        renderBookList();
    }});
}});

// --- CSV Export ---
document.getElementById('exportBtn').addEventListener('click', () => {{
    const dates = getFilteredDates();

    // Collect all category names across all books
    const allCats = new Set();
    asins.forEach(asin => {{
        Object.values(DATA.books[asin].subcategories).forEach(cat => allCats.add(cat.name));
    }});
    const catNames = [...allCats].sort();

    // Header: Date, Title, Format, Overall Rank, then one column per category
    const header = ['Date', 'Title', 'Format', 'Overall Rank', ...catNames];
    const rows = [header];

    asins.forEach(asin => {{
        const book = DATA.books[asin];
        const title = getCleanTitle(book.name);
        const fmt = getFormat(book.name);
        const fmtLabel = fmt === 'all' ? '' : fmt.charAt(0).toUpperCase() + fmt.slice(1);

        // Build a lookup: catName -> {{ date -> rank }}
        const catLookup = {{}};
        Object.values(book.subcategories).forEach(cat => {{
            catLookup[cat.name] = cat.data;
        }});

        dates.forEach(date => {{
            const overall = book.overall[date];
            // Only include dates where we have data for this book
            const hasCatData = catNames.some(cn => catLookup[cn] && catLookup[cn][date] !== undefined);
            if (overall === undefined && !hasCatData) return;

            const row = [date, title, fmtLabel, overall !== undefined ? overall : ''];
            catNames.forEach(cn => {{
                const val = catLookup[cn] && catLookup[cn][date];
                row.push(val !== undefined ? val : '');
            }});
            rows.push(row);
        }});
    }});

    const csv = rows.map(r => r.map(v => {{
        const s = String(v);
        return s.includes(',') || s.includes('"') ? '"' + s.replace(/"/g, '""') + '"' : s;
    }}).join(',')).join('\\n');

    const blob = new Blob([csv], {{ type: 'text/csv' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'bsr-data-' + new Date().toISOString().split('T')[0] + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}});

// --- Initial render ---
const latestFormatted = new Date(latestDate + 'T00:00:00').toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
document.getElementById('rankHeader').textContent = 'Overall Rank (' + latestFormatted + ')';
renderOverviewChart();
renderBookList();
</script>
</body>
</html>"""
    return html


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate BSR dashboard HTML")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Database path")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT), help="Output HTML path")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: database not found at {db_path}")
        return

    book_titles = load_books_json()
    data = query_all_data(db_path)
    html = generate_html(data, book_titles)

    out_path = Path(args.out)
    out_path.write_text(html)
    print(f"Dashboard written to {out_path}")


if __name__ == "__main__":
    main()
