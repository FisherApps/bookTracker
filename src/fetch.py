"""HTTP fetching for Amazon product pages with CAPTCHA detection."""

import os
from dataclasses import dataclass
from typing import Literal

import requests

# Optional Cloudflare Worker proxy. When set, requests go through the Worker
# (running on CF edge IPs) instead of direct to Amazon. Set both vars to use it.
_PROXY_URL = os.environ.get("AMAZON_PROXY_URL", "").rstrip("/")
_PROXY_TOKEN = os.environ.get("AMAZON_PROXY_TOKEN", "")

_CAPTCHA_STRINGS = [
    "Type the characters you see in this image",
    "To discuss automated access to Amazon data please contact",
    "Sorry, we just need to make sure you're not a robot",
    "api-services-support@amazon.com",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


@dataclass(slots=True)
class FetchResult:
    asin: str
    status: Literal["ok", "http_error", "captcha", "timeout"]
    http_status: int | None
    html: str | None
    reason_detail: str | None


def fetch_product_html(asin: str, session: requests.Session) -> FetchResult:
    """Fetch a product page from Amazon. Does not retry internally."""
    if _PROXY_URL and _PROXY_TOKEN:
        url = f"{_PROXY_URL}/dp/{asin}"
        headers = {**_HEADERS, "Authorization": f"Bearer {_PROXY_TOKEN}"}
    else:
        url = f"https://www.amazon.com/dp/{asin}"
        headers = _HEADERS

    try:
        response = session.get(url, headers=headers, timeout=20)
    except (requests.ConnectionError, requests.Timeout, requests.RequestException) as e:
        return FetchResult(
            asin=asin,
            status="timeout",
            http_status=None,
            html=None,
            reason_detail=type(e).__name__,
        )

    # 503 → captcha
    if response.status_code == 503:
        return FetchResult(
            asin=asin,
            status="captcha",
            http_status=503,
            html=None,
            reason_detail="503",
        )

    # Other non-200 → http_error
    if response.status_code != 200:
        return FetchResult(
            asin=asin,
            status="http_error",
            http_status=response.status_code,
            html=None,
            reason_detail=f"HTTP {response.status_code}",
        )

    # 200 — check body for CAPTCHA signals
    body = response.text
    for signal in _CAPTCHA_STRINGS:
        if signal in body:
            return FetchResult(
                asin=asin,
                status="captcha",
                http_status=200,
                html=None,
                reason_detail="captcha_string_detected",
            )

    # 200 but no BSR block → treat as captcha/failure
    if "Best Sellers Rank" not in body:
        return FetchResult(
            asin=asin,
            status="captcha",
            http_status=200,
            html=None,
            reason_detail="missing_bsr_block",
        )

    # Success
    return FetchResult(
        asin=asin,
        status="ok",
        http_status=200,
        html=body,
        reason_detail=None,
    )
