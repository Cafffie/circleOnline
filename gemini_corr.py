"""Curve Online extractor implementation using the framework."""
import json
import random
import re
import sys
import time
from datetime import datetime, date
from dateutil import parser

import pandas as pd
from selenium.webdriver.common.by import By
from seleniumbase import SB

from utils.base_extractor import BaseExtractor
from utils.logger import setup_logger
from utils.scraping_helpers import (
    extract_postcode,
    get_city_country_uk,
    get_currency_from_price,
    get_scrape_datetime,
    human_delay,
    human_scroll,
    parse_booking_dates,
    standardize_category,
    normalize_country,
    convert_to_24hr,
    format_datetime_key,
)

from .curve_online_config import (
    DEFAULT_THEATRE_DETAILS,
    COOKIE_BTN_XPATH,
    PAGES,
    DEFAULT_CURRENCY, 
    SELECTORS
)

logger = setup_logger(__name__, log_to_file=False)


class CurveOnlineExtractor(BaseExtractor):
    """Extractor for Curve Online website."""

    def __init__(self, local_test=False, show_count=2, **kwargs):
        super().__init__(
            site_id="curve_online",
            log_to_file=False,
            log_to_terminal=True,
            local_test=local_test,
            show_count=show_count,
            **kwargs,
        )
        self.all_data = []

    def safe_get(self, sb, url, wait=10):
        try:
            self.custom_logger.info("Loading URL: %s", url)
            sb.uc_open_with_reconnect(url, reconnect_time=wait if wait > 4 else 4)
            if (
                "captcha" in sb.get_current_url().lower()
                or "distil" in sb.get_page_source().lower()
            ):
                self.custom_logger.warning("Bot protection detected. Solving...")
                sb.uc_gui_handle_captcha()
                time.sleep(random.uniform(2, 4))
            self.custom_logger.info("Page loaded successfully: %s", url)
            return True
        except Exception as e:
            self.custom_logger.error(
                "Failed to load page: %s | Exception: %s", url, repr(e)
            )
            return None

    def accept_cookies(self, sb):
        cookie_xpath = SELECTORS.get("cookie_button", COOKIE_BTN_XPATH)
        try:
            if sb.is_element_visible(cookie_xpath):
                human_delay(1, 2.5)
                sb.click(cookie_xpath)
                human_delay(2, 3)
        except Exception:
            pass

    def _parse_date(self, text: str) -> str | None:
        try:
            dt = parser.parse(text, dayfirst=True, fuzzy=True)
            if dt.date() < date.today():
                dt = dt.replace(year=dt.year + 1)
            return dt.strftime("%Y-%m-%d")
        except Exception as e:
            self.custom_logger.error(f"_parse_date failed for '{text}': {e}")
            return None

    def get_show_links(self, sb):
        elements = sb.find_elements(By.CSS_SELECTOR, "article.listing__item a")
        return list(set([e.get_attribute("href") for e in elements if e.get_attribute("href")]))

    def _get_show_title(self, sb) -> str | None:
        """Extract show title."""
        try:
            return sb.get_text("header.flush--right h1.major-title").strip() or None
        except Exception:
            return None
            
    def _get_terminal_dates(self, sb) -> str | None:
        """Extract show header dates."""
        try:
            terminal_date = sb.get_text("header.flush--right .show__date")
            return terminal_date.strip() if terminal_date else None
        except Exception as e:
            self.custom_logger.debug(f"Terminal date extraction failed: {e}")
            return None

    def _get_theatre_address(self, sb) -> dict:
        """Extract theatre address."""
        data = {}
        try:
            address_element = sb.find_element(".white-wrapper p.AreaAndVenueDetails")
            address = address_element.text.replace("\n", "") if address_element else ""
            if address:
                data["address"] = address
                parts = address.split(",")
                curve = parts[1] if len(parts) > 1 else ""
                theatre = parts[0]

                venue_string = f"{curve} {theatre}"
                data["venue"] = venue_string.strip() if "curve" in address.lower() else "Studio Theatre"
                
                postcode = extract_postcode(address, region="UK")
                if postcode:
                    city, country = get_city_country_uk(postcode)
                    data["city"] = city
                    data["country"] = country
            return data if data else DEFAULT_THEATRE_DETAILS
        except Exception as e:
            self.custom_logger.info(f"Address extraction failed, fallback to default: {e}")
            return DEFAULT_THEATRE_DETAILS

    def _extract_performances(self, sb) -> list[dict]: 
        """Parses performance instances directly from Curve's date markers."""
        performances = []

        try:
            year_element = sb.get_text(".show__time, .show__date")
            self.custom_logger.info(f"Year element found: {year_element}")
            year = year_element.strip().split(" ")[-1].strip()
            if not year.isdigit():
                year = str(datetime.now().year)
        except Exception as e:
            year = str(datetime.now().year) 
            self.custom_logger.info(f"Year parse error, Fallback to current year: {e}")
                
        try:
            date_blocks = sb.find_elements(By.CSS_SELECTOR, ".listing--info, article.listing__info")
            self.custom_logger.info(f"Found {len(date_blocks)} performance dates")

            for block in date_blocks:
                try:
                    anchor = block.find_element(By.TAG_NAME, "a")
                    booking_url = anchor.get_attribute("href") if anchor else None
                    if not booking_url:
                        continue
                        
                    date_elem = block.find_element(By.CSS_SELECTOR, ".listing__date time")
                    raw_date_text = date_elem.get_attribute("textContent").strip() if date_elem else ""
                    
                    time_elem = block.find_element(By.CSS_SELECTOR, ".listing__time time")
                    raw_time_text = time_elem.get_attribute("textContent").strip() if time_elem else ""
                    
                    if not raw_date_text or not raw_time_text:
                        continue
                        
                    date_string = f"{raw_date_text} {year} {raw_time_text}"
                    date_ymd = self._parse_date(date_string)
                    if not date_ymd:
                        continue

                    time_hm = convert_to_24hr(raw_time_text)
                    if not time_hm:
                        continue
              
                    performances.append({
                        "date": date_ymd,
                        "time": time_hm,  
                        "booking_url": booking_url
                    })
                except Exception as inner_e:
                    self.custom_logger.debug(f"Date block parsing error: {inner_e}")
                    continue

        except Exception as e:
            self.custom_logger.debug(f"Error extracting performances: {e}")
        return performances

    def extract_seats(self, sb) -> tuple:
        """Extracts seats and pricing from the currently open SVG modal."""

        max_capacity = None
        currency = None
        seat_list = []
        
        try:
            seats = sb.find_elements(By.CSS_SELECTOR, "div.SeatingArea img[class*='Seat'], rect.seat")
            self.custom_logger.info(f"Found {len(seats)} unique seats.")

            for seat in seats:
                tooltip = seat.get_attribute("tooltip") or seat.get_attribute("title") or ""
                
                perf_capacity = len(seats) if seats else None
                if max_capacity is None or perf_capacity > max_capacity:
                    max_capacity = perf_capacity
                
                if currency is None and tooltip:
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
        
        return seat_list, currency, max_capacity

    def extract_seat_metrics(self, sb, performances):
        """Extracts seats and pricing from internal ticket frame configurations."""
        venue_details = DEFAULT_THEATRE_DETAILS.copy()
        venue_extracted = False
        seat_pricing = {}
        encountered_no_seatmap = False
        currency = None
        capacity = None
        
        for i, perf in enumerate(performances, start=1):
            key = format_datetime_key(perf["date"], perf["time"])
            if not key:
                continue

            self.custom_logger.info(f" [{i}/{len(performances)}] {perf['date']} {perf['time']}")

            try:
                if not self.safe_get(sb, perf["booking_url"]):
                    seat_pricing[key] = []
                    continue
                
                human_delay(4, 5.5)

                if sb.is_element_present("#SpektrixIFrame"):
                    sb.switch_to_frame("#SpektrixIFrame")
                    
                    if not venue_extracted:
                        venue_details = self._get_theatre_address(sb) 
                        venue_extracted = True

                    if sb.is_element_present("div.SeatingArea img, rect.seat"):
                        seat_list, perf_currency, perf_capacity = self.extract_seats(sb)
                        if seat_list:
                            seat_pricing[key] = seat_list
                            if perf_currency:
                                currency = perf_currency
                            if perf_capacity:
                                capacity = perf_capacity
                        else:
                            seat_pricing[key] = []
                    else:
                        seat_pricing[key] = []
                        encountered_no_seatmap = True
                else:
                    seat_pricing[key] = []
                    encountered_no_seatmap = True  
                    self.custom_logger.info(f"No seat map iframe available for {perf['date']} {perf['time']}")

            except Exception as e:
                seat_pricing[key] = []
                encountered_no_seatmap = True  
                self.custom_logger.warning(f"Seat extraction error: {e}")
            finally:
                try:
                    sb.switch_to.default_content()
                except:
                    pass

            human_delay(3, 5)

        if encountered_no_seatmap and all(len(s) == 0 for s in seat_pricing.values()):
            self.custom_logger.info("All performances lack a seat map layout.")

        return seat_pricing, currency, capacity, venue_details

    def _scrape_one_show(self, sb, show_url: str, category: str) -> dict | None:
        """Scrape a single show page end-to-end."""
        if not self.safe_get(sb, show_url):
            return None

        title = self._get_show_title(sb)
        if not title:
            self.custom_logger.warning("No title found for: %s", show_url)

        open_date, close_date = None, None
        terminal_date = self._get_terminal_dates(sb)
        if terminal_date:
            booking_dates = parse_booking_dates(terminal_date)
            open_date = booking_dates.get("start_date")
            close_date = booking_dates.get("end_date")
        
        self.accept_cookies(sb)
        human_delay(2, 4)

        self.custom_logger.info("Category: %s", category)
        self.custom_logger.info("Title: %s", title)
        self.custom_logger.info("-" * 50)

        human_scroll(sb)
        time.sleep(2)

        performances = self._extract_performances(sb)
        if not performances:
            self.custom_logger.warning(f"No performances found for '{title}', skipping")
            return None

        sorted_dates = sorted([p["date"] for p in performances])
        if not open_date:
            open_date = sorted_dates[0]
        if not close_date:
            close_date = sorted_dates[-1]
            
        seat_pricing, currency, capacity, venue_details = self.extract_seat_metrics(sb, performances)

        venue_url = sb.get_current_url()
        venue_name = venue_details.get("venue", "Curve Theatre")
        address = venue_details.get("address", "")
        city = venue_details.get("city", "Leicester")
        country = normalize_country(venue_details.get("country", "UK"))

        return {
            "title": title,
            "category": category,
            "venue": venue_name,
            "venue_url": venue_url,
            "address": address,
            "city": city,
            "country": country,
            "open_date": open_date,
            "close_date": close_date,
            "booking_start_date": open_date,
            "booking_end_date": close_date,
            "upcoming_performances": [
                {"date": p["date"], "time": p["time"]} for p in performances
            ],
            "seat_pricing": seat_pricing,
            "capacity": capacity,
            "currency": currency or DEFAULT_CURRENCY,
            "is_limited_run": None,
            "scrape_datetime": get_scrape_datetime(),
        }

    def _scrape_shows(self, sb, show_links: list, category: str) -> None:
        """Scrape individual show pages with multi-pass retry."""
        _MAX_PASSES = 3
        pending = list(show_links)

        for _pass in range(1, _MAX_PASSES + 1):
            if not pending:
                break

            self.custom_logger.info(
                "Show pass %d/%d — %d show(s)", _pass, _MAX_PASSES, len(pending)
            )
            still_pending = []

            for show_url in pending:
                row = self._scrape_one_show(sb, show_url, category)
                if row is None:
                    still_pending.append(show_url)
                    self.custom_logger.warning(
                        "Pass %d: show deferred — %s", _pass, show_url
                    )
                else:
                    self.all_data.append(row)
                    self.log_record(row)
                    human_delay(5, 10)

            pending = still_pending

            if pending and _pass < _MAX_PASSES:
                human_scroll(sb)
                human_delay(15, 30)

    def extract(self) -> bytes:
        """Open SB session, scrape all shows, populate self.all_data, return JSON bytes."""
        self.all_data = []

        with SB(
            uc=True,
            test=True,
            headless=True,
            browser="chrome",
            locale="en-US",
        ) as sb:
            self.custom_logger.info("Starting extraction from Curve Online")

            for url, category in PAGES:
                if not self.safe_get(sb, url):
                    continue

                human_delay(3, 5)
                sb.maximize_window()
                self.accept_cookies(sb)

                show_links = self.get_show_links(sb)

                if self.local_test:
                    show_links = show_links[:self.show_count]

                self._scrape_shows(sb, show_links, category)

        return json.dumps(self.all_data, default=str).encode("utf-8")

    def _parse(self, _raw: bytes):
        df = pd.DataFrame(self.all_data)
        return df


def main():
    extractor = CurveOnlineExtractor(
        save_csv_locally=False, 
        csv_incremental_mode=False
    )
    result = extractor.run()
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
