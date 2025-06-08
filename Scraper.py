import requests
from bs4 import BeautifulSoup
import os
import pandas as pd
from datetime import datetime
import json
from collections import OrderedDict
import re
import time
import logging

# ---------------------------
# Config
# ---------------------------
BASE_URL = "https://nidhiratna.com"
MAIN_SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": BASE_URL
}

CSV_FILENAME = "nidhi_prices.csv"
# PREV_CSV_FILENAME removed from saving here on purpose
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds

# Setup logging WITHOUT timestamps
logging.basicConfig(
    format='%(levelname)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger()

# ---------------------------
# Normalize price string
# ---------------------------
def normalize_price(price):
    if not isinstance(price, str):
        return ""
    price = price.replace('\n', ' ').replace('\r', ' ').strip()
    price = re.sub(r'\s+', ' ', price)
    match = re.search(r'[$₹]?\d+(?:,\d{3})*(?:\.\d{2})?', price)
    return match.group(0).replace(',', '') if match else ""

# ---------------------------
# Request with retry
# ---------------------------
def requests_get_with_retry(url, headers=None, timeout=10):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as e:
            logger.warning(f"Request failed (attempt {attempt}/{MAX_RETRIES}) for URL: {url} - {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"Giving up on URL: {url}")
                return None
            else:
                time.sleep(RETRY_BACKOFF * attempt)

# ---------------------------
# Fetch product sitemap URLs dynamically
# ---------------------------
logger.info("📡 Discovering product sitemaps...")
response = requests_get_with_retry(MAIN_SITEMAP_URL, headers=HEADERS)
if response is None:
    logger.error("❌ Failed to load master sitemap, exiting.")
    exit(1)

soup = BeautifulSoup(response.content, "xml")
sitemap_urls = [loc.text.strip() for loc in soup.find_all("loc") if "sitemap_products" in loc.text]
logger.info(f"✅ Found {len(sitemap_urls)} product sitemaps.\n")

# ---------------------------
# Fetch product URLs from all sitemaps
# ---------------------------
logger.info("📥 Fetching product URLs from sitemaps...")
product_urls = []

for sitemap_url in sitemap_urls:
    logger.info(f"Fetching: {sitemap_url}")
    response = requests_get_with_retry(sitemap_url, headers=HEADERS)
    if response is None:
        logger.error(f"❌ Failed to load sitemap: {sitemap_url}")
        continue

    soup = BeautifulSoup(response.content, "xml")
    urls = [loc.text for loc in soup.find_all("loc") if "/products/" in loc.text]
    product_urls.extend(urls)

product_urls = list(OrderedDict.fromkeys(product_urls))
logger.info(f"✅ Total unique product URLs found: {len(product_urls)}\n")

# ---------------------------
# Scraping functions
# ---------------------------
def scrape_title(soup):
    selectors = [
        "h1.product-title", "h1.product__title", "h1.h2", "h1",
        'meta[property="og:title"]'
    ]
    for sel in selectors:
        if sel.startswith("meta"):
            tag = soup.find("meta", property="og:title")
            if tag and tag.get("content"):
                return tag["content"].strip()
        else:
            tag = soup.select_one(sel)
            if tag and tag.text.strip():
                return tag.text.strip()
    if soup.title and soup.title.text.strip():
        return soup.title.text.strip()
    return "No title found"

def scrape_sku(soup, url):
    sku_selectors = ["span.sku", "span.product-sku", "span.variant-sku", "div.sku", '[class*="sku"]']
    for sel in sku_selectors:
        tag = soup.select_one(sel)
        if tag and tag.text.strip():
            return tag.text.strip()
    ld_json = soup.find("script", type="application/ld+json")
    if ld_json:
        try:
            data = json.loads(ld_json.string)
            if isinstance(data, dict) and "sku" in data:
                return data["sku"]
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "sku" in entry:
                        return entry["sku"]
        except Exception:
            pass
    return url.rstrip('/').split('/')[-1]

def scrape_prices(soup):
    price_containers = soup.select('div#ProductPrice, div.product__price, div.product-price')
    sale_price = None
    regular_price = None

    for container in price_containers:
        price_tags = container.find_all(['span', 'div'], recursive=True)
        prices_found = []
        for tag in price_tags:
            text = tag.get_text(strip=True)
            price = normalize_price(text)
            if price and price != "$0.00":
                prices_found.append(price)
        prices_found = sorted(set(prices_found), key=lambda x: float(x.replace('$','').replace('₹','')))
        if len(prices_found) == 1:
            sale_price = prices_found[0]
            regular_price = prices_found[0]
        elif len(prices_found) >= 2:
            sale_price = prices_found[0]
            regular_price = prices_found[-1]
        if sale_price and regular_price:
            break

    return sale_price or "", regular_price or ""

def scrape_availability(soup):
    sold_out_texts = ['sold out', 'out of stock', 'unavailable']
    page_text = soup.get_text(separator=' ').lower()
    if any(x in page_text for x in sold_out_texts):
        return "Sold Out"
    buttons = soup.find_all('button')
    for btn in buttons:
        btn_text = btn.get_text(strip=True).lower()
        if 'add to cart' in btn_text or 'buy now' in btn_text or 'add to bag' in btn_text:
            if not btn.has_attr('disabled'):
                return "Available"
    return "Unknown"

# ---------------------------
# Scrape products
# ---------------------------
results = []
errors = []

logger.info("🚀 Starting product scraping...")

for i, url in enumerate(product_urls, 1):
    logger.info(f"Scraping product {i}: {url}")
    response = requests_get_with_retry(url, headers=HEADERS)
    if response is None:
        logger.error(f"❌ Failed to fetch product page: {url}")
        errors.append(url)
        continue

    soup = BeautifulSoup(response.content, "html.parser")

    title = scrape_title(soup)
    sku = scrape_sku(soup, url)
    sale_price, regular_price = scrape_prices(soup)
    availability = scrape_availability(soup)

    results.append({
        "Title": title,
        "SKU": sku,
        "Sale_Price": sale_price,
        "Regular_Price": regular_price,
        "Availability": availability,
        "Link": url,
        "Date": datetime.today().strftime('%Y-%m-%d')
    })

    logger.info(f"→ Title: {title}")
    logger.info(f"→ SKU: {sku}")
    logger.info(f"→ Sale Price: {sale_price}")
    logger.info(f"→ Regular Price: {regular_price}")
    logger.info(f"→ Availability: {availability}\n")

    time.sleep(0.5)

new_df = pd.DataFrame(results).drop_duplicates(subset="Link")

# ---------------------------
# Compare with previous data
# ---------------------------
if os.path.exists(CSV_FILENAME):
    logger.info("\n🔍 Comparing with previous data...\n")
    try:
        old_df = pd.read_csv(CSV_FILENAME)
        if "Link" in old_df.columns and "Link" in new_df.columns:
            merged = pd.merge(old_df, new_df, on="Link", suffixes=("_old", "_new"))

            for _, row in merged.iterrows():
                old_sale = row.get("Sale_Price_old", "")
                new_sale = row.get("Sale_Price_new", "")
                old_regular = row.get("Regular_Price_old", "")
                new_regular = row.get("Regular_Price_new", "")

                if (old_sale != new_sale or old_regular != new_regular) and old_sale and new_sale:
                    logger.info(f"💡 Price changed for: {row['Title_new']}")
                    logger.info(f"Old Sale Price: {old_sale}")
                    logger.info(f"Old Regular Price: {old_regular}")
                    logger.info(f"New Sale Price: {new_sale}")
                    logger.info(f"New Regular Price: {new_regular}")
                    logger.info(f"Link: {row['Link']}")
                    logger.info("-" * 40)

            old_links = set(old_df["Link"])
            new_links = set(new_df["Link"])

            new_products = [item for item in results if item["Link"] not in old_links]
            removed_products = old_links - new_links

            if new_products:
                logger.info("\n🆕 New products listed since last run:")
                for p in new_products:
                    logger.info(f"Title: {p['Title']}")
                    logger.info(f"Sale Price: {p['Sale_Price']}")
                    logger.info(f"Regular Price: {p['Regular_Price']}")
                    logger.info(f"Availability: {p['Availability']}")
                    logger.info(f"SKU: {p['SKU']}")
                    logger.info(f"Link: {p['Link']}")
                    logger.info("-" * 40)
                logger.info(f"\n📈 Total new products added: {len(new_products)}")

            if removed_products:
                logger.info("\n⚠️ Removed products since last run:")
                for link in removed_products:
                    logger.info(link)
                logger.info(f"Total removed: {len(removed_products)}")
        else:
            logger.warning("⚠️ 'Link' column missing in old or new data. Skipping comparison.")
    except Exception as e:
        logger.error(f"❌ Failed to load or compare with old CSV: {e}")
else:
    logger.info("📦 No previous data file found. Saving new data as baseline.\n")

# ---------------------------
# Save to CSV (Only current data)
# ---------------------------
new_df.to_csv(CSV_FILENAME, index=False, encoding='utf-8')
logger.info(f"\n✅ All data saved to {CSV_FILENAME}")

if errors:
    logger.warning(f"\n⚠️ Failed to scrape {len(errors)} product pages:")
    for err_url in errors:
        logger.warning(err_url)
