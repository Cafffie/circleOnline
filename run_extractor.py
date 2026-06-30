"""Blumenthal Arts extractor implementation using the framework."""

import json
import re
import sys
from datetime import date, datetime

import pandas as pd
from dateutil import parser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils.base_extractor import BaseExtractor
from utils.logger import setup_logger
from utils.scraping_helpers import (
    accept_cookies,
    parse_booking_dates,
    convert_to_24hr,
    extract_postcode,
    format_datetime_key,
    get_city_country_uk,
    get_currency_from_price,
    get_scrape_datetime,
    human_delay,
    human_scroll,
    
    normalize_country,
    standardize_category,
)

from .blumenthal_arts_config import (
    DEFAULT_THEATRE_DETAILS,
    MAX_RETRIES,
    PAGES,
    QUEUE_COOKIES,
    RETRY_DELAY,
    RUN_HEADLESS,
    THEATRE_DETAILS_MAP,
)

logger = setup_logger(__name__, log_to_file=False)


class BlumenthalArtsExtractor(BaseExtractor):
    """Extractor for Blumenthal Arts website using SeleniumBase."""

    def __init__(self, local_test=False, show_count=2, **kwargs):
        super().__init__(
            site_id="blumenthal_arts",
            log_to_file=False,
            log_to_terminal=True,
            local_test=local_test,
            show_count=show_count,
            **kwargs,
        )
        self.all_data = []

    def safe_get(self, sb, url: str, wait: int = 10) -> bool | None:
        """Safely load a URL using SeleniumBase UC mode."""
        try:
            self.custom_logger.info("Loading URL: %s", url)

            sb.uc_open_with_reconnect(url, reconnect_time=max(wait, 4))
            sb.wait_for_ready_state_complete()

            current_url = sb.get_current_url().lower()
            page_source = sb.get_page_source().lower()

            if "captcha" in current_url or "distil" in page_source:
                self.custom_logger.warning("Bot protection detected. Solving...")
                sb.uc_gui_handle_captcha()
                human_delay(2, 4)

            self.custom_logger.info("Page loaded successfully: %s", url)
            return True

        except Exception as e:
            self.custom_logger.error(
                "Failed to load page: %s | Exception: %s",
                url,
                repr(e),
            )
            return None


    def safe_find_child(element, xpath, many=False):
    """Safely find child element(s)."""
    try:
        return (
            element.find_elements(By.XPATH, xpath)
            if many
            else element.find_element(By.XPATH, xpath)
        )
    except Exception as e:
        logger.debug("Child element not found for XPath: %s | %s", xpath, e)
        return [] if many else None

    def get_links(self, sb, xpath):
        elements = sb.find_elements(By.XPATH, xpath)
        return [e.get_attribute("href") for e in elements if e.get_attribute("href")]

    def _parse_date(self, text: str) -> date | None:
        try:
            dt = parser.parse(text, dayfirst=True, fuzzy=True)
            if dt.date() < date.today():
                dt = dt.replace(year=dt.year + 1)
            return dt
        except Exception:
            return None
    

    def _get_theatre_address(self, sb) -> dict:
        """Extract theatre address."""
        data = {}
        try:
            address = sb.find_element(SELECTORS["theatre_address"]).strip().text.replace("\n", "")
            if address:
                data["address"] = address
                parts = address.split(",")
                curve = parts[1]
                theatre = parts[0]

                venue_string = f"{curve} {theatre}"
                data["venue"] = venue_string.strip() if "curve" in full_text.lower() else "Studio Theatre"
                
                postcode = extract_postcode(address, region="UK")
                city, country = get_city_country_uk(postcode)
                data["city"] = city
                data["country"] = country

        except Exception as e:
            self.custom_logger.info(f" Address extraction failed: {e}", "warning")
            return DEFAULT_THEATRE_DETAILS["address"]

        return data

    def _get_show_title(self, sb) -> str | None:
        """Extract show title."""
        try:
            return sb.get_text(SELECTORS["title"]).strip() or None
        except Exception:
            return None


    def _get_show_dates(self, sb) -> str | None:
        """Extract and parse show open and close dates."""
        try:
            # Mon 13 - Sat 18 Jul 2026 / Sat 4 Jul 2026
            terminal_date = sb.get_text(SELECTORS["terminal_date"])
            parsed_date = parse_booking_dates(terminal_date)

            open_date = parsed_date.get("start_date")
            close_date = parsed_date.get("end_date")
        except Exception as e:
            self.custom_logger.debug(f" terminal date extraction failed: {e}", "warning")
            return None, None
        return open_date, close_date
    

    def _extract_event_list(sb, category: str) -> list[dict]:
    """
    Parses individual cards inside the main events list holder from Curve's layout structure.
    """
    shows = []
    shows_cards = sb.find_elements(By.CSS_SELECTOR, "article.listing__item")
    self.custom_logger.info(f" Found {len(shows_cards)} show cards")

    for i, card in enumerate(shows_cards, start=1):
        try:
            title_element = card.find_element("h2.media__title")
            title = title_element.get_attribute("textContent").strip()
            link = card.find_element(By.TAG_NAME, "a").get_attribute("href")

            self.custom_logger.info(f" [{i}/{len(shows_cards)}] {title}")

            shows.append({
                "title": title,
                "event_url": link,
                "category": category
            })
        except Exception as e:
            self.custom_logger.debug(f" Event list item parse error at block index {i}: {e}", "warning")
            continue

    return shows


def _extract_performances(self, sb) -> list[dict]:
    """Parses performance instances directly from Curve's single or continuous date markers."""
    performances = []

    try:
        # Mon 13 - Sat 18 Jul 2026 / Sat 4 Jul 2026
        year_element = sb.find_element(By.CSS_SELECTOR, ".show__time, .show__date")
        self.custom_logger.info(f" Year element found")
        split_year = year_element.get_attribute("textContent").strip().split(" ")[-1].strip()
        if len(split_year) == 4 and split_year.isdigit():
            year = split_year
    except Exception as e:
        year = str(datetime.now().year) # Fallback to current year
        self.custom_logger.info(f" Year parse error, Fallback to current year : {e}", "warning")
            
    try:
        date_blocks = db.find_elements(By.CSS_SELECTOR, "article.listing__info")
        self.custom_logger.info(f" Performance Date element found")

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
        self.custom_logger.debug(f" Error extracting performances: {e}")

    return performances


def extract_seats(self, sb)-> tuple:
     """Extracts seats and pricing from the currently open SVG modal."""

    max_capacity = None
    currency = None
    try:
        seats = sb.find_elements(By.CSS_SELECTOR, "div.SeatingArea img[class*='Seat'], rect.seat")
        self.custom_logger.info(f" Found {len(seats)} unique seats. ")

        seat_list = []
        for seat in seats:
            tooltip = seat.get_attribute("tooltip") or seat.get_attribute("title") or ""
            
            perf_capacity = len(seats) if seats else None
            if max_capacity is None or perf_capacity > max_capacity:
                max_capacity = perf_capacity
            
            if currency is None:
                currency = get_currency_from_price(tooltip)

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

    except Exception as e:
        self.custom_logger.debug(f"Seat canvas extraction subloop failure: {e}")
        break
    
    self.custom_logger.info(
            f" Total capacity: {max_capacity} seats ({len(seat_list)} priced)")
    return seat_list, currency, max_capacity


def extract_seat_metrics(self, sb, performances):
    """Extracts seats and pricing from internal ticket frame configurations."""
    venue_details = {"venue": None, "address": None, "city": None, "country": "UK"}
    venue_extracted = False
    seat_pricing = {}

    encountered_no_seatmap = False
    
    for i, perf in enumerate(performances, start=1):
        
        key = format_datetime_key(perf["date"], perf["time"])
        if not key:
            continue

        # Confirm if sold out
        if not perf.get("booking_url"):
            seat_pricing[key] = []
            continue
        
        self.custom_logger.info(f" [{i}/{len(performances)}] {perf['date']} {perf['time']}")

        try:
            sb.open(perf["booking_url"])

            sb.wait_for_element_present("SpektrixIFrame", timeout=12)
            iframes = sb.find_elements(By.ID, "SpektrixIFrame")
            if iframes:
                iframe = iframes[0]
                sb.switch_to.frame(iframe)
                
                # --- SINGLE-PASS ADDRESS EXTRACTION ---
                if not venue_extracted:
                    venue_details = _get_theatre_address(self, sb)
                    venue_extracted = True
                # ------------------------------------------------
                sb.wait_for_element_present("div.SeatingArea img, rect.seat", timeout=12)
                seat_list, currency, capacity = self.extract_seats(sb)

                if seat_list:
                    seat_pricing[key] = seat_list  
            
                self.custom_logger.info(f" {len(seat_list)} seats extracted")
            else:
                # MISSING SEATMAP: Page loaded but iframe layout isn't there
                seat_pricing[key] = []
                encountered_no_seatmap = True  # <--- Flagged
                self.custom_logger.info(
                    f" No seat map available for {perf['date']} {perf['time']}"
                )

        except Exception as e:
            seat_pricing[key] = []
            encountered_no_seatmap = True  # <--- Flagged
            self.custom_logger.warning(f" Seat extraction error: {e}")
            perf["capacity"] = None
        finally:
            try:
                sb.switch_to.default_content()
            except:
                pass

        human_delay(*DELAY_BETWEEN_PERFS)

    # =================================================================================
    # CONDITIONAL CHECK:
    # Only clear to {} if we actually hit "no seatmap" issues AND everything is empty.
    # =================================================================================
    if encountered_no_seatmap and all(
        len(seat_list) == 0 for seat_list in seat_pricing.values()
    ):
        self.custom_logger.info(
            " All performances lack a seat map layout. Resetting seat_pricing = {}"
        )
        seat_pricing = {}
    # =================================================================================

    self.custom_logger.info(" Seat extraction flow processed")
    return seat_pricing, currency, venue_details

 
 def _log_show_summary(self, record: dict) -> None:
        seat_pricing = record.get("seat_pricing") or {}
        perfs = record.get("upcoming_performances") or []
        divider = "  " + "━" * 54
        lines = [
            divider,
            f"  ✓  {record['title']}  [{record['category']}]",
            f"     Venue    : {record['venue']}, {record['city']}, {record['country']}",
            f"     Run      : {record['open_date']} → {record['close_date']}",
            f"     Capacity : {record['capacity']}  |  Currency: {record['currency']}",
            f"     Performances ({len(perfs)}):",
        ]
        for p in perfs:
            key = f"{p['date']} {p['time']}"
            seats = seat_pricing.get(key, [])
            seat_label = (
                f"{len(seats)} seats" if seats else "No seat map availabe or sold out"
            )
            lines.append(f"       • {key}  →  {seat_label}")
        lines.append(divider)
        self.custom_logger.info("\n".join(lines))


    def _scrape_show(self, sb, show: dict) -> dict | None:
        for attempt in range(1, 4):
            try:
                sb.open(show["event_url"])
                break
            except (TimeoutException, WebDriverException) as exc:
                self.custom_logger.warning(
                    f"  Load attempt {attempt}/3 failed for {show['title']!r}: "
                    f"{type(exc).__name__}"
                )
                if attempt == 3:
                    raise
                human_delay(1.5, 3.0)
        accept_cookies(sb, xpath=COOKIE_BTN_XPATH)
        human_scroll(sb)

        performances = self._extract_performances(sb)

        if not performances:
            self.custom_logger.warning(
                f"  No performances found for '{show['title']}', skipping"
            )
            return None
            
        open_date, close_date = self._get_show_dates(sb)

        seat_pricing, currency, capacity, venue_details = self.extract_seat_metrics(self, sb, performances)
    

        if performances:
            sorted_dates = sorted([p["date"] for p in performances])
            open_date = sorted_dates[0]
            close_date = sorted_dates[-1]
        else:
            open_date = datetime.now().strftime("%Y-%m-%d")
            close_date = datetime.now().strftime("%Y-%m-%d")

        return {
            "title": show["title"],
            "venue_url": show["event_url"],
            "category": standardize_category(show["category"]),
            "venue": venue,
            "address": venue_details["address"],
            "city": venue_details["city"],
            "country": normalize_country(venue_details["country"]),
            "open_date": open_date,
            "close_date": close_date,
            "booking_start_date": open_date,
            "booking_end_date": close_date,
            "upcoming_performances": [
                {"date": p["date"], "time": p["time"]} for p in performances
            ],
            "capacity": capacity,
            "currency": currency,
            "is_limited_run": None,
            "seat_pricing": seat_pricing,
            "scrape_datetime": get_scrape_datetime(),
        }

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if not df.empty and "is_limited_run" in df.columns:
            df["is_limited_run"] = None
        if not df.empty and "capacity" in df.columns:
            df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce").astype(
                "Int64"
            )
        return df


    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if not df.empty and "is_limited_run" in df.columns:
            df["is_limited_run"] = None
        if not df.empty and "capacity" in df.columns:
            df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce").astype(
                "Int64"
            )
        return df

    def _parse(self, raw: bytes) -> pd.DataFrame:
        data = json.loads(raw.decode("utf-8"))
        df = pd.DataFrame(data)
        if not df.empty and "capacity" in df.columns:
            if df["capacity"].notna().any():
                df["capacity"] = df["capacity"].astype(pd.Int64Dtype())
        self.custom_logger.info(f"Parsed {len(df)} record(s)")
        return df



def main():
    extractor = BlumenthalArtsExtractor(
        save_csv_locally=False, 
        csv_incremental_mode=False
    )
    result = extractor.run()
    logger.info("Extraction result: %s", result)


if __name__ == "__main__":
    main()    
