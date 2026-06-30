import re
import os
import time
import logging
import pandas as pd
from datetime import datetime, date
from dateutil import parser

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import undetected_chromedriver as uc

# ============================================================
# CONFIG & LOGGING
# ============================================================
RUN_HEADLESS = True
OUTPUT_FILE = "output1.csv"
PAGES = [
    ("https://www.curveonline.co.uk/whats-on/?genre-filter=musical", "Musical"),
    ("https://www.curveonline.co.uk/whats-on/?genre-filter=drama", "Play")
]

if not os.path.exists("log"):
    os.makedirs("log")

logging.basicConfig(
    filename="log/scrape.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def log(msg, level="info"):
    print(f"[LOG] {msg}")
    if level == "error": logging.error(msg)
    elif level == "warning": logging.warning(msg)
    else: logging.info(msg)


# ============================================================
# BROWSER SETUP
# ============================================================
def setup_browser():
    log("🚀 Starting browser...")
    options = uc.ChromeOptions()
    if RUN_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")

    driver = uc.Chrome(options=options, version_main=148)
    driver.implicitly_wait(10)
    return driver


def safe_get(driver, url, retries=3):
    for attempt in range(1, retries + 1):
        try:
            log(f"🌍 Loading page ({attempt}/{retries}): {url}")
            driver.get(url)
            return True
        except Exception as e:
            log(f"❌ Load failed: {e}", "error")
            time.sleep(2)
    return False


def handle_cookies(driver):
    try:
        # Extracted directly from your initial working script configuration
        wait = WebDriverWait(driver, 20)
        allow_all = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(., 'Allow all') or contains(., 'Accept')]"
                )
            )
        )
        allow_all.click()
        log("Cookies accepted.")
        time.sleep(5)
    except Exception:
        log("Cookie banner not found or skipped.", "warning")


def scroll_to_load_all(driver):
    log("⬇️ Scrolling page...")
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    log("✅ Finished scrolling")


def _parse_date(text: str) -> date | None:
    try:
        dt = parser.parse(text, dayfirst=True, fuzzy=True)
        if dt.date() < date.today():
            dt = dt.replace(year=dt.year + 1)
        return dt.strftime("%Y-%m-%d")
    except Exception as e:
        log(f"_parse_date failed for '{text}': {e}")
        return None


# ============================================================
# CLEAN CURRENCY TEXT
# ============================================================
def detect_currency(text):
    if not text: return None
    if "£" in text: return "GBP"
    elif "$" in text: return "USD"
    elif "€" in text: return "EUR"
    return None


# ============================================================
# 1. VENUE DETAILS FUNCTION
# ============================================================
def _get_venue_details(driver) -> dict:
    """Extract venue address from Curve Theatre's native structural layout."""
    data = {"venue": None, "address": None, "city": None, "country": "UK"}

    try:
        footer_addr = driver.find_element(By.CSS_SELECTOR, ".white-wrapper p.AreaAndVenueDetails")
        full_text = footer_addr.get_attribute("textContent").strip().replace("\n", "")
        log(f"Address : {full_text.strip()}")

        # Theatre, Curve, 60 Rutland Street, Leicester, LE1 1SB
        if full_text.strip():        
            data["address"] = full_text

            parts = full_text.split(",")
            curve = parts[1]
            theatre = parts[0]

            venue_string = f"{curve} {theatre}"
            data["venue"] = venue_string.strip() if "curve" in full_text.lower() else "Studio Theatre"
            data["city"] = parts[3].strip()
    except Exception as e:
        log(f"⚠️ Address extraction failed: {e}", "warning")
        pass

    return data


# ============================================================
# 2. EVENT LIST SELECTION
# ============================================================
def _extract_event_list(driver, category: str) -> list[dict]:
    """
    Parses individual cards inside the main events list holder from Curve's layout structure.
    """
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "article.listing__item")
            )
        )
    except Exception:
        log("  No event card found on listing page")
        return []

    shows = []
    shows_cards = driver.find_elements(By.CSS_SELECTOR, "article.listing__item")
    log(f"📦 Found {len(shows_cards)} show cards")

    for i, card in enumerate(shows_cards, start=1):
        try:
            title_element = card.find_element(By.CSS_SELECTOR, "h2.media__title")
            title = title_element.get_attribute("textContent").strip()
            link = card.find_element(By.TAG_NAME, "a").get_attribute("href")

            log(f" ➤ [{i}/{len(shows_cards)}] {title}")

            shows.append({
                "title": title,
                "event_url": link,
                "category": category
            })
        except Exception as e:
            log(f"⚠️ Event list item parse error at block index {i}: {e}", "warning")
            continue
    return shows

# ============================================================
# 3. OPEN AND CLOSE DATES
# ============================================================
def _extract_dates(driver) -> list[dict]:
    """
    Parses individual cards inside the main events list holder from Curve's layout structure.
    """
    date_list = []

    date_element = driver.find_element(By.CSS_SELECTOR, "article.listing__item show__date")
    dates = date_element.get_attribute("textContent").strip()

# ============================================================
# 3. PERFORMANCE TIMELINE PROCESSING
# ============================================================
def _extract_performances(driver) -> list[dict]:
    """Parses performance instances directly from Curve's single or continuous date markers."""
    performances = []

    try:
        # Mon 13 - Sat 18 Jul 2026 / Sat 4 Jul 2026
        year_element = driver.find_element(By.CSS_SELECTOR, ".show__time, .show__date")
        log(f" Year element found")

        split_year = year_element.get_attribute("textContent").strip().split(" ")[-1].strip()
        if len(split_year) == 4 and split_year.isdigit():
            year = split_year
    except Exception as e:
        year = str(datetime.now().year) # Fallback to current year
        log(f" Year parse error, Fallback to current year : {e}", "warning")
            
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".listing--info, article.listing__info"))
        )
        log(f" Date element found")

        date_blocks = driver.find_elements(By.CSS_SELECTOR, "article.listing__info")

        for block in date_blocks:
            booking_url = block.find_element(By.TAG_NAME, "a").get_attribute("href")
            raw_date_text = block.find_element(By.CSS_SELECTOR, ".listing__date time").get_attribute("textContent").strip()
            raw_time_text = block.find_element(By.CSS_SELECTOR, ".listing__time time").get_attribute("textContent").strip()

            date_string = f"{raw_date_text} {year} {raw_time_text}"
            parsed_dt = parser.parse(date_string)

            date_ymd = parsed_dt.strftime("%Y-%m-%d")
            time_hm = parsed_dt.strftime("%H:%M")
      
            
            performances.append({
                "date": date_ymd,
                "time": time_hm,  
                "booking_url": booking_url
            })

    except Exception as e:
        log(f"  Error extracting performances: {e}")

    return performances


# ============================================================
# SEAT PRICING
# ============================================================
def extract_all_seats(driver, performances):
    """Extracts seats and pricing from internal ticket frame configurations."""
    venue_details = {"venue": None, "address": None, "city": None, "country": "UK"}
    venue_extracted = False
    seat_pricing = {}
    currency = None
    
    for i, perf in enumerate(performances, start=1):
        try:
            start = time.time()
            log(f"   🔄 [{i}/{len(performances)}] {perf['date']} {perf['time']}")

            driver.get(perf["booking_url"])

            iframe = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "SpektrixIFrame"))
            )
            driver.switch_to.frame(iframe)

            # --- SINGLE-PASS ADDRESS EXTRACTION ---
            if not venue_extracted:
                venue_details = _get_venue_details(driver)
                venue_extracted = True
            # ------------------------------------------------

            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.SeatingArea img, rect.seat"))
            )

            seats = driver.find_elements(By.CSS_SELECTOR, "div.SeatingArea img[class*='Seat'], rect.seat")
            log(f"📦 Found {len(seats)} unique seats. ")

            seat_list = []
            for seat in seats:
                tooltip = seat.get_attribute("tooltip") or seat.get_attribute("title") or ""
                
                detected_currency = detect_currency(tooltip)
                if detected_currency and currency is None:
                    currency = detected_currency

                if not tooltip:
                    continue

                match = re.search(r"([A-Z]+\d+)\s*-\s*£?([\d,.]+)", tooltip)
                if not match:
                    continue
                seat_id = match.group(1)
                ticket_price = float(match.group(2).replace(",", ""))

                seat_list.append({
                    "seat": seat_id,
                    "ticket_price": ticket_price
                })

            perf["capacity"] = len(seats) if seats else None
            key = f"{perf['date']} {perf['time']}"
            seat_pricing[key] = seat_list

            log(f" ✅ Seat lists: {len(seat_list)} | Time: {round(time.time()-start,2)}s")

        except Exception as e:
            log(f"❌ Seat extraction skipped or unavailable for current iframe context: {e}", "warning")
            perf["capacity"] = None
        finally:
            try:
                driver.switch_to.default_content()
            except:
                pass

    log("✅ Seat extraction flow processed")
    return seat_pricing, currency, venue_details


# ============================================================
# MAIN APPLICATION FLOW
# ============================================================
def scrape_shows():
    log("🚀 SCRAPER STARTED")

    driver = setup_browser()
    all_rows = []

    try:
        for page_idx, (url, category) in enumerate(PAGES, start=1):
            log(f"\n🌍 CATEGORY CORRELATION {page_idx}/{len(PAGES)} → {category}")

            if not safe_get(driver, url):
                continue

            handle_cookies(driver)
            scroll_to_load_all(driver)

            shows = _extract_event_list(driver, category)

            for i, show in enumerate(shows[:1], start=1):
                log(f"\n🎭 EVENT SPECIFIC EXTRACTION {i}/{len(shows)} → {show['title']}")

                if not safe_get(driver, show["event_url"]):
                    continue

                #handle_cookies(driver)
                scroll_to_load_all(driver)
                scrape_dt = datetime.now().strftime("%Y-%m-%d %H:%M")

                #venue_details = _get_venue_details

                raw_performances = _extract_performances(driver)

                if not raw_performances:
                    log(f"⚠️ No active performances extracted for '{show['title']}', row skipped.")
                    continue

                dates = [p["date"] for p in raw_performances if p.get("date")]
                open_date = min(dates) if dates else ""
                close_date = max(dates) if dates else ""

                formatted_performances = str([
                    {"date": p["date"], "time": p["time"]} for p in raw_performances
                ])

                seat_pricing, currency, venue_details = extract_all_seats(driver, raw_performances)
                formatted_seat_pricing = repr(seat_pricing) if seat_pricing else "{}"

                capacity = max([p.get("capacity", 0) for p in raw_performances], default=0)

                
                row = {
                    "title": show["title"],
                    "venue_url": show["event_url"],
                    "category": show["category"],
                    "venue": venue_details["venue"],
                    "address": venue_details["address"],
                    "city": venue_details["city"],
                    "country": venue_details["country"],
                    "open_date": open_date,
                    "close_date": close_date,
                    "booking_start_date": open_date,
                    "booking_end_date": close_date,
                    "upcoming_performances": formatted_performances,
                    "capacity": capacity if capacity > 0 else None,
                    "currency": currency if seat_pricing else None,
                    "is_limited_run": None,
                    "seat_pricing": formatted_seat_pricing,
                    "scrape_datetime": scrape_dt
                }
                all_rows.append(row)
                log(f"✅ Extracted Row Record Saved: {show['title']}")

    except Exception as e:
        log(f"⚠️ Error occurred while scraping shows: {e}", "warning")

    finally:
        driver.quit()
        log("🛑 Browser processes completely shut down.")

    # Build CSV in strict canonical order
    canonical_columns = [
        "title", "venue_url", "category", "venue", "address", "city", "country",
        "open_date", "close_date", "booking_start_date", "booking_end_date",
        "upcoming_performances", "capacity", "currency", "is_limited_run",
        "seat_pricing", "scrape_datetime"
    ]

    if all_rows:
        df = pd.DataFrame(all_rows)
        df = df.reindex(columns=canonical_columns)
    else:
        df = pd.DataFrame(columns=canonical_columns)

    df.to_csv(OUTPUT_FILE, index=False)
    log(f"✅ Scraped data saved to: {OUTPUT_FILE} ({len(df)} lines generated).")


if __name__ == "__main__":
    scrape_shows()
