import os
import re
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ── Common price selectors to try (in order) ──────────────────────
# The script tries each one until it finds a valid price
PRICE_SELECTORS = [
    # Schema.org (universal standard — works on thousands of sites)
    "[itemprop='price']",
    "meta[itemprop='price']",
    "meta[property='product:price:amount']",

    # Nike
    "[data-test='product-price']",

    # Amazon
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    ".a-price .a-offscreen",
    "span.a-price-whole",

    # Lazada
    "span.pdp-price",
    "span.pdp-price_type_normal",

    # Shopee
    "div.pmmxKx",
    "._3n5NQx",
    "span.colour-49A8DC",

    # Zalora
    "span.price",
    "span.sale-price",

    # Harvey Norman / generic retail
    "span.price-current",
    "span.special-price",
    ".product-price",
    ".price-box",

    # WooCommerce (powers millions of sites)
    "p.price ins .woocommerce-Price-amount",
    "p.price .woocommerce-Price-amount",
    ".woocommerce-Price-amount",

    # Shopify (powers millions of stores)
    "span.price__current",
    "[data-product-price]",
    ".product__price",
    "span.price-item--regular",

    # Generic fallbacks
    "[class*='price']:not([class*='old']):not([class*='was']):not([class*='original'])",
    "[id*='price']",
    ".current-price",
    ".sale-price",
    ".offer-price",
]

# ── Sites that NEED Selenium (JavaScript-rendered) ─────────────────
SELENIUM_DOMAINS = [
    "nike.com",
    "adidas.com",
    "lazada.com",
    "shopee.com",
    "zalora.com",
    "amazon.com",
    "amazon.com.my",
    "asos.com",
    "uniqlo.com",
    "zara.com",
    "hm.com",
]

# ── Sites protected by Cloudflare ─────────────────────────────────
CLOUDFLARE_DOMAINS = [
    "shopee.com",
    "shopee.com.my",
]

# ── Load products from .env ───────────────────────────────────────
def load_products() -> list:
    products = []
    i = 1
    while True:
        url       = os.getenv(f"PRODUCT_{i}_URL")
        threshold = os.getenv(f"PRODUCT_{i}_THRESHOLD")
        name      = os.getenv(f"PRODUCT_{i}_NAME", f"Product {i}")

        if not url or not threshold:
            break  # No more products found

        products.append({
            "name":      name,
            "url":       url,
            "threshold": float(threshold),
        })
        i += 1

    return products

# ── Auto-detect which method to use ───────────────────────────────
def detect_method(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    domain = domain.replace("www.", "")

    for cf_domain in CLOUDFLARE_DOMAINS:
        if cf_domain in domain:
            print(f"   🛡  Detected Cloudflare protection → using cloudscraper")
            return "cloudscraper"

    for js_domain in SELENIUM_DOMAINS:
        if js_domain in domain:
            print(f"   ⚙️  Detected JS-rendered site → using Selenium")
            return "selenium"

    print(f"   📄 Trying plain requests first...")
    return "requests"

# ── Fetch methods ─────────────────────────────────────────────────
def fetch_with_requests(url: str) -> BeautifulSoup | None:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except Exception as e:
        print(f"   ⚠️  requests failed: {e}")
        return None

def fetch_with_selenium(url: str) -> BeautifulSoup | None:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        driver  = webdriver.Chrome(service=service, options=options)

        driver.get(url)
        time.sleep(4)  # Wait for JS to render price
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        return soup

    except ImportError:
        print("   ⚠️  Selenium not installed. Run: pip install selenium webdriver-manager")
        return None
    except Exception as e:
        print(f"   ⚠️  Selenium failed: {e}")
        return None

def fetch_with_cloudscraper(url: str) -> BeautifulSoup | None:
    try:
        import cloudscraper
        scraper  = cloudscraper.create_scraper()
        response = scraper.get(url, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except ImportError:
        print("   ⚠️  cloudscraper not installed. Run: pip install cloudscraper")
        return None
    except Exception as e:
        print(f"   ⚠️  cloudscraper failed: {e}")
        return None

# ── Smart fetch with auto-fallback ────────────────────────────────
def fetch_page(url: str) -> BeautifulSoup | None:
    method = detect_method(url)

    if method == "cloudscraper":
        soup = fetch_with_cloudscraper(url)
        if not soup:
            print("   🔄 Falling back to Selenium...")
            soup = fetch_with_selenium(url)

    elif method == "selenium":
        soup = fetch_with_selenium(url)
        if not soup:
            print("   🔄 Falling back to requests...")
            soup = fetch_with_requests(url)

    else:  # requests
        soup = fetch_with_requests(url)
        if not soup:
            print("   🔄 Falling back to Selenium...")
            soup = fetch_with_selenium(url)

    return soup

# ── Auto-detect price from soup ───────────────────────────────────
def extract_price(soup: BeautifulSoup) -> tuple[float, str] | None:
    """
    Tries every known selector until a valid price is found.
    Returns (price_float, matched_selector) or None if not found.
    """
    for selector in PRICE_SELECTORS:
        try:
            tags = soup.select(selector)

            for tag in tags:
                # Get content from attribute or text
                raw = (
                    tag.get("content")   # meta tags store price in content=""
                    or tag.get("data-price")
                    or tag.get_text(strip=True)
                )

                if not raw:
                    continue

                # Strip everything except digits and dot
                cleaned = re.sub(r"[^\d.]", "", str(raw)).strip()

                if not cleaned:
                    continue

                # Handle multiple dots (e.g. "1.299.00")
                parts = cleaned.split(".")
                if len(parts) > 2:
                    cleaned = "".join(parts[:-1]) + "." + parts[-1]

                price = float(cleaned)

                # Sanity check — ignore 0, and ignore absurd values
                if 0.1 < price < 1_000_000:
                    return price, selector

        except Exception:
            continue

    return None

# ── Send Telegram alert ───────────────────────────────────────────
def send_telegram_alert(product: dict, price: float) -> None:
    currency = "RM" if ".my" in product["url"] else "$"

    message = (
        f"🔔 *Price Drop Alert!*\n\n"
        f"🛍 *{product['name']}*\n"
        f"💰 Current price: *{currency} {price:.2f}*\n"
        f"🎯 Your threshold: {currency} {product['threshold']:.2f}\n\n"
        f"👉 [View Product]({product['url']})"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":               TELEGRAM_CHAT_ID,
        "text":                  message,
        "parse_mode":            "Markdown",
        "disable_web_page_preview": False,
    }

    response = requests.post(api_url, json=payload, timeout=10)
    response.raise_for_status()
    print("   ✅ Telegram alert sent!")

# ── Main ──────────────────────────────────────────────────────────
def main():
    products = load_products()

    if not products:
        print("❌ No products found in .env file!")
        print("   Add PRODUCT_1_URL, PRODUCT_1_THRESHOLD, PRODUCT_1_NAME to your .env")
        return

    print(f"\n{'='*52}")
    print(f"  Price Drop Tracker — {len(products)} product(s) to check")
    print(f"{'='*52}\n")

    for product in products:
        print(f"🔍 {product['name']}")
        print(f"   {product['url']}")

        try:
            soup = fetch_page(product["url"])

            if not soup:
                print("   ❌ Could not fetch the page. Skipping.\n")
                continue

            result = extract_price(soup)

            if not result:
                print("   ❌ Could not find price on page.")
                print("   💡 Tip: Inspect the page manually to find the price selector.")
                print()
                continue

            price, selector = result
            print(f"   ✅ Price found via: {selector}")
            print(f"   💲 Current price:  {price:.2f}")
            print(f"   🎯 Threshold:      {product['threshold']:.2f}")

            if price < product["threshold"]:
                print("   📉 BELOW threshold! Sending alert...")
                send_telegram_alert(product, price)
            else:
                print("   📈 Above threshold. No alert needed.")

        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")

        print()
        time.sleep(3)

if __name__ == "__main__":
    main()