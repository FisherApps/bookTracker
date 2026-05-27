"""Re-parse saved HTML files without hitting the network.

Usage:
    python -m src.reparse path/to/file.html
    python -m src.reparse path/to/directory/
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.parse import ParseError, parse_product_page


def reparse_file(filepath: Path) -> dict:
    """Parse a single HTML file and return the result as a dict."""
    html = filepath.read_text()
    # Use filename stem as a placeholder ASIN
    asin = filepath.stem
    parsed = parse_product_page(html, asin=asin)
    return asdict(parsed)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.reparse <html_file_or_directory>", file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])

    if target.is_file():
        try:
            result = reparse_file(target)
            print(json.dumps(result, indent=2))
        except ParseError as e:
            print(f"ParseError: {e}", file=sys.stderr)
            sys.exit(1)
    elif target.is_dir():
        for html_file in sorted(target.glob("*.html")):
            try:
                result = reparse_file(html_file)
                print(json.dumps(result, indent=2))
            except ParseError as e:
                print(f"ParseError ({html_file.name}): {e}", file=sys.stderr)
    else:
        print(f"Error: {target} is not a file or directory", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
