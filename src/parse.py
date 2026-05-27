"""HTML parser for Amazon product pages — extracts BSR data."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


class ParseError(Exception):
    """Raised when the HTML cannot be parsed into rank data."""


@dataclass(slots=True)
class RankEntry:
    category_id: str        # 'books' for overall, else numeric string
    category_name: str
    rank: int


@dataclass(slots=True)
class ParsedPage:
    asin: str
    title: str | None
    author: str | None
    book_format: str | None  # 'Kindle', 'Hardcover', 'Paperback', etc.
    ranks: list[RankEntry]


def parse_product_page(html: str, asin: str) -> ParsedPage:
    """Parse an Amazon product page HTML and extract BSR data.

    Raises ParseError if no rank block is found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Title
    title = None
    title_el = soup.find(id="productTitle")
    if title_el:
        title = title_el.get_text(strip=True)

    # --- Author (first byline link)
    author = None
    byline = soup.find(id="bylineInfo")
    if byline:
        a = byline.find("a")
        if a:
            author = a.get_text(strip=True)

    # --- Format (Kindle, Hardcover, Paperback)
    book_format = None
    selected_swatch = soup.find("div", class_=lambda c: c and "swatchElement" in c and "selected" in c and "unselected" not in c)
    if selected_swatch:
        swatch_id = selected_swatch.get("id", "")
        # ID looks like "tmm-grid-swatch-HARDCOVER" or "tmm-grid-swatch-KINDLE"
        if "KINDLE" in swatch_id.upper():
            book_format = "Kindle"
        elif "HARDCOVER" in swatch_id.upper():
            book_format = "Hardcover"
        elif "PAPERBACK" in swatch_id.upper():
            book_format = "Paperback"

    # --- BSR block: find the <li> whose text starts with "Best Sellers Rank"
    bsr_li = None
    for li in soup.find_all("li"):
        txt = li.get_text(" ", strip=True)
        if txt.startswith("Best Sellers Rank"):
            bsr_li = li
            break

    if bsr_li is None:
        raise ParseError(f"No BSR block found for ASIN {asin}")

    ranks: list[RankEntry] = []

    # Overall rank: text before the nested <ul>
    head_text_parts = []
    for child in bsr_li.descendants:
        if getattr(child, "name", None) == "ul":
            break
        if isinstance(child, str):
            head_text_parts.append(child)
    head_text = " ".join(t.strip() for t in head_text_parts if t.strip())

    m = re.search(r"#([\d,]+)\s+in\s+([A-Za-z][A-Za-z &()'-]*?)(?:\s*\(|$)", head_text)
    if m:
        ranks.append(RankEntry(
            category_id="books",
            category_name=m.group(2).strip(),
            rank=int(m.group(1).replace(",", "")),
        ))

    # Sub-ranks from ul.zg_hrsr
    zg = bsr_li.find("ul", class_="zg_hrsr")
    if zg:
        for sub in zg.find_all("li"):
            sub_text = sub.get_text(" ", strip=True)
            sm = re.match(r"#([\d,]+)\s+in\s+(.+)", sub_text)
            if not sm:
                continue
            category_name = sm.group(2).strip()
            category_id = None
            link = sub.find("a", href=True)
            if link:
                idm = re.search(r"/bestsellers/books/(\d+)/", link["href"])
                if idm:
                    category_id = idm.group(1)
            if category_id is None:
                continue
            ranks.append(RankEntry(
                category_id=category_id,
                category_name=category_name,
                rank=int(sm.group(1).replace(",", "")),
            ))

    if not ranks:
        raise ParseError(f"BSR block found but no ranks extracted for ASIN {asin}")

    return ParsedPage(asin=asin, title=title, author=author, book_format=book_format, ranks=ranks)
