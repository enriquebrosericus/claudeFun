"""
Amazon Price Tracker — SMALLRIG Compartment Aluminum Case (B0GQH1D6Y4)

Scrapes the product page periodically and exposes price data as Prometheus metrics.
Serves metrics on http://0.0.0.0:8000/metrics

Anti-bot notes:
  - Rotates User-Agent strings
  - Adds realistic browser headers
  - Respects a configurable scrape interval (default 5 min)
  - Backs off exponentially on failures
"""

import logging
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
ASIN = os.getenv("ASIN", "B0GQH1D6Y4")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "SMALLRIG Compartment Aluminum Case")
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "300"))   # seconds
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0"))   # 0 = disabled

AMAZON_URL = f"https://www.amazon.com/dp/{ASIN}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# ── Prometheus Metrics ────────────────────────────────────────────────────────
LABELS = ["asin", "product"]

product_price = Gauge(
    "amazon_product_price_usd",
    "Current listed price in USD",
    LABELS,
)
product_original_price = Gauge(
    "amazon_product_original_price_usd",
    "Original (was/list) price in USD, before discounts",
    LABELS,
)
product_discount_pct = Gauge(
    "amazon_product_discount_percent",
    "Discount percentage off original price",
    LABELS,
)
product_in_stock = Gauge(
    "amazon_product_in_stock",
    "1 if in stock, 0 if out of stock",
    LABELS,
)
product_rating = Gauge(
    "amazon_product_rating",
    "Average star rating (0–5)",
    LABELS,
)
product_review_count = Gauge(
    "amazon_product_review_count",
    "Total number of customer reviews",
    LABELS,
)
scrape_duration = Histogram(
    "amazon_scrape_duration_seconds",
    "Time taken to fetch and parse the product page",
    LABELS,
    buckets=[0.5, 1, 2, 5, 10, 30],
)
scrape_errors = Counter(
    "amazon_scrape_errors_total",
    "Number of failed scrape attempts",
    LABELS + ["error_type"],
)
scrapes_total = Counter(
    "amazon_scrapes_total",
    "Total number of scrape attempts (success + failure)",
    LABELS,
)
last_scrape_ts = Gauge(
    "amazon_last_scrape_timestamp_seconds",
    "Unix timestamp of the last successful scrape",
    LABELS,
)
product_info = Info(
    "amazon_product",
    "Static product metadata",
)


# ── Data Model ────────────────────────────────────────────────────────────────
@dataclass
class ProductData:
    price: Optional[float]
    original_price: Optional[float]
    in_stock: bool
    rating: Optional[float]
    review_count: Optional[int]
    title: Optional[str]


# ── Scraper ───────────────────────────────────────────────────────────────────
def build_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def parse_price(text: str) -> Optional[float]:
    """Extract a float price from strings like '$49.99' or '49.99'."""
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if match:
        return float(match.group().replace(",", ""))
    return None


def scrape_product(url: str) -> ProductData:
    """Fetch and parse the Amazon product page."""
    resp = requests.get(url, headers=build_headers(), timeout=15)
    resp.raise_for_status()

    # Amazon sometimes redirects to a CAPTCHA page
    if "robot" in resp.url.lower() or "captcha" in resp.text.lower():
        raise RuntimeError("CAPTCHA / bot-detection triggered")

    soup = BeautifulSoup(resp.text, "lxml")

    # ── Title ──────────────────────────────────────────────────────────────
    title_tag = soup.find("span", id="productTitle")
    title = title_tag.get_text(strip=True) if title_tag else None

    # ── Price ──────────────────────────────────────────────────────────────
    price: Optional[float] = None

    # Primary price: .a-price .a-offscreen (whole + fraction combined)
    price_span = soup.select_one(".a-price .a-offscreen")
    if price_span:
        price = parse_price(price_span.get_text())

    # Fallback: #priceblock_ourprice (older layout)
    if price is None:
        pb = soup.find("span", id="priceblock_ourprice")
        if pb:
            price = parse_price(pb.get_text())

    # ── Original / Was Price ───────────────────────────────────────────────
    original_price: Optional[float] = None
    was_span = soup.select_one(".a-text-price .a-offscreen")
    if was_span:
        original_price = parse_price(was_span.get_text())

    # ── Discount ───────────────────────────────────────────────────────────
    discount_pct: float = 0.0
    if price and original_price and original_price > price:
        discount_pct = round((1 - price / original_price) * 100, 1)

    # ── Stock ──────────────────────────────────────────────────────────────
    availability_div = soup.find("div", id="availability")
    in_stock = True  # assume in stock unless we see otherwise
    if availability_div:
        avail_text = availability_div.get_text(strip=True).lower()
        in_stock = "in stock" in avail_text or "currently unavailable" not in avail_text

    # ── Rating ─────────────────────────────────────────────────────────────
    rating: Optional[float] = None
    rating_span = soup.select_one("span[data-hook='rating-out-of-text']")
    if rating_span:
        rating = parse_price(rating_span.get_text())
    else:
        alt_rating = soup.select_one("#acrPopover")
        if alt_rating and alt_rating.get("title"):
            rating = parse_price(alt_rating["title"])

    # ── Review Count ───────────────────────────────────────────────────────
    review_count: Optional[int] = None
    review_span = soup.find("span", id="acrCustomerReviewText")
    if review_span:
        m = re.search(r"[\d,]+", review_span.get_text())
        if m:
            review_count = int(m.group().replace(",", ""))

    return ProductData(
        price=price,
        original_price=original_price,
        in_stock=in_stock,
        rating=rating,
        review_count=review_count,
        title=title,
    )


# ── Prometheus Update ─────────────────────────────────────────────────────────
def update_metrics(data: ProductData) -> None:
    labels = {"asin": ASIN, "product": PRODUCT_NAME}

    if data.price is not None:
        product_price.labels(**labels).set(data.price)
        log.info("Price: $%.2f", data.price)
    else:
        log.warning("Could not parse price — metric not updated")

    if data.original_price is not None:
        product_original_price.labels(**labels).set(data.original_price)
        pct = round((1 - (data.price or data.original_price) / data.original_price) * 100, 1)
        product_discount_pct.labels(**labels).set(pct)

    product_in_stock.labels(**labels).set(1 if data.in_stock else 0)

    if data.rating is not None:
        product_rating.labels(**labels).set(data.rating)

    if data.review_count is not None:
        product_review_count.labels(**labels).set(data.review_count)

    last_scrape_ts.labels(**labels).set(time.time())


# ── Main Loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("Starting Amazon Price Tracker")
    log.info("  ASIN:     %s", ASIN)
    log.info("  Product:  %s", PRODUCT_NAME)
    log.info("  URL:      %s", AMAZON_URL)
    log.info("  Interval: %ds", SCRAPE_INTERVAL)
    log.info("  Metrics:  http://0.0.0.0:%d/metrics", METRICS_PORT)

    product_info.info({
        "asin": ASIN,
        "name": PRODUCT_NAME,
        "url": AMAZON_URL,
    })

    start_http_server(METRICS_PORT)
    log.info("Prometheus metrics server started on port %d", METRICS_PORT)

    labels = {"asin": ASIN, "product": PRODUCT_NAME}
    backoff = SCRAPE_INTERVAL

    while True:
        scrapes_total.labels(**labels).inc()
        start = time.time()
        try:
            with scrape_duration.labels(**labels).time():
                data = scrape_product(AMAZON_URL)
            update_metrics(data)
            backoff = SCRAPE_INTERVAL  # reset backoff on success
            log.info("Scrape OK (%.2fs). Sleeping %ds.", time.time() - start, SCRAPE_INTERVAL)
            time.sleep(SCRAPE_INTERVAL)

        except requests.exceptions.Timeout:
            scrape_errors.labels(**labels, error_type="timeout").inc()
            log.warning("Timeout after %.2fs. Backoff %ds.", time.time() - start, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)

        except requests.exceptions.HTTPError as e:
            scrape_errors.labels(**labels, error_type=f"http_{e.response.status_code}").inc()
            log.warning("HTTP %s. Backoff %ds.", e.response.status_code, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)

        except RuntimeError as e:
            scrape_errors.labels(**labels, error_type="captcha").inc()
            log.warning("%s. Backoff %ds.", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)

        except Exception as e:
            scrape_errors.labels(**labels, error_type="unknown").inc()
            log.exception("Unexpected error: %s. Backoff %ds.", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)


if __name__ == "__main__":
    main()
