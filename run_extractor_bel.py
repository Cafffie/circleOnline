"""Belfast Grand Opera House extractor implementation using the framework."""
import json
import random
import re
import sys
import time
from datetime import datetime

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
)

from .belfast_grand_opera_house_config import BASE_URLS, DEFAULT_CURRENCY, SELECTORS

logger = setup_logger(__name__, log_to_file=False)


class BelfastGrandOperaHouseExtractor(BaseExtractor):
    """Extractor for Belfast Grand Opera House website."""

    def __init__(self, local_test=False, show_count=2, **kwargs):
        super().__init__(
            site_id="belfast_grand_opera_house",
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
        cookie_xpath = SELECTORS["cookie_button"]
        try:
            if sb.is_element_visible(cookie_xpath):
                human_delay(1, 2.5)
                sb.click(cookie_xpath)
                human_delay(2, 3)
        except Exception:
            pass

    def get_pagination_links(self, sb):
        pages = sb.find_elements(SELECTORS["pagination_link"])
        links = []
        for p in pages:
            link = p.get_attribute("href")
            page_number = p.get_attribute("data-number")
            if link:
                links.append((page_number, link))
        return links

    def get_links(self, sb, xpath):
        elements = sb.find_elements(By.XPATH, xpath)
        return [e.get_attribute("href") for e in elements if e.get_attribute("href")]

    def _get_show_title(self, sb) -> str | None:
        """Extract show title."""
        try:
            return sb.get_text"h2.media__title").strip() or None
        except Exception:
            return None
            
    def _get_terminal_dates(self, sb) -> str | None: # Fixed type hinting hint to match output tuple
        """Extract show header dates."""
        try:
            terminal_date = sb.get_text("article.listing__item show__date")
        except Exception as e:
            self.custom_logger.debug(f" terminal date extraction failed: {e}", "warning")
            return None

    def _get_theatre_address(self, sb) -> str | None: 
        """Extract theatre venue address."""
        try:
            address = sb.find_element(".white-wrapper p.AreaAndVenueDetails").text.replace("\n", "")
        except Exception as e:
            self.custom_logger.warning(f" Address extraction failed, fallback to default: {e}", "warning")
            return DEFAULT_THEATRE_DETAILS["address"]

    def _get_theatre_venue(self, address) -> str | None: 
        """Extract theatre venue from address."""
        try:
            if address:
                # Theatre, Curve, 60 Rutland Street, Leicester, LE1 1SB
                address_parts = address.split(",")
                if len(address_parts) > 3
                    curve = address_parts[1]
                    theatre = address_parts[0]
                    venue_string = f"{curve} {theatre}"
                    venue = venue_string.strip() if "curve" in address.lower() else "Studio Theatre" 
        except Exception as e:
            self.custom_logger.warning(f" Venue extraction failed, fallback to default: {e}", "warning")
            return DEFAULT_THEATRE_DETAILS["venue"]

    def _extract_performances(self, sb) -> list[dict]: 
        """Parses performance instances directly from Curve's single or continuous date markers."""
        performances = []

        try:
            year_element = sb.get_text( ".show__time, .show__date")
            self.custom_logger.info(f" Year element found")
            year = year_element.strip().split(" ")[-1].strip()
        except Exception as e:
            year = str(datetime.now().year) 
            self.custom_logger.info(f" Year parse error, Fallback to current year : {e}", "warning")
                
        try:
            date_blocks = sb.find_elements(By.CSS_SELECTOR, "article.listing__info") # Fixed: db -> sb
            self.custom_logger.info(f" Found {len(date_blocks)} performance dates")

            for block in date_blocks:
                booking_url = block.find_element(By.TAG_NAME, "a").get_attribute("href")
                if not booking_url:
                    continue
                    
                raw_date_text = block.find_element(By.CSS_SELECTOR, ".listing__date time").get_attribute("textContent").strip()
                if not raw_date_text:
                    continue
                    
                raw_time_text = block.find_element(By.CSS_SELECTOR, ".listing__time time").get_attribute("textContent").strip()
                if not raw_time_text:
                    continue
                    
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

         

    def _scrape_one_show(self, sb, show_url: str, category: str) -> dict | None:
        """Scrape a single show page end-to-end.

        Returns a completed row dict on success, or None if the show page
        did not render (bot challenge, timeout) — the caller retries.
        """
        if not self.safe_get(sb, show_url):
            return None

        self.accept_cookies(sb)
        human_delay(2, 4)

        title = self._get_show_title(sb)
        if not title:
            self.custom_logger.warning("No title found for: %s", show_url)

        terminal_date = self._get_terminal_dates(sb)
        if terminal_date:
            booking_dates = parse_booking_dates(terminal_date)
            open_date = booking_dates.get("start_date")
            close_date = booking_dates.get("end_date")
        
        address = self._get_theatre_address(sb)
        venue_url = sb.get_current_url()
        venue_name =  self._get_theatre_venue(sb, address)
        self.custom_logger.info("Venue name: %s", venue_name)
        self.custom_logger.info("Venue address: %s", address)
        if address:
            postcode = extract_postcode(address, region="UK")
            city, country = get_city_country_uk(postcode)
       
        self.custom_logger.info("Category: %s", category)
        self.custom_logger.info("Title: %s", title)
        self.custom_logger.info("Terminal: %s", terminal_date)
        self.custom_logger.info("Venue: %s", venue_name)
        self.custom_logger.info("Address: %s", address)
        self.custom_logger.info("City: %s", city)
        self.custom_logger.info("Country: %s", country)
        self.custom_logger.info("Open Date: %s", open_date)
        self.custom_logger.info("Close Date: %s", close_date)
        self.custom_logger.info("-" * 50)

        sb.execute_script(
            "document.querySelector('button[aria-label*=\"Book Tickets\"]').click();"
        )
        human_delay(10, 12.5)
        human_scroll(sb)
        time.sleep(3)

        upcoming_performances = self._extract_performances(sb)
        seat_pricing = {}
        performance_links = {}  # href → datetime_key

        instances = sb.find_elements(By.CSS_SELECTOR, SELECTORS["event_instance"])
        self.custom_logger.info("Found %d instances", len(instances))

        for inst in instances:
            try:
                date_elem = inst.find_element(
                    By.CSS_SELECTOR, SELECTORS["instance_date"]
                )
                date_text = sb.execute_script(
                    "return arguments[0].textContent.trim();", date_elem
                )
                if not date_text:
                    continue

                time_elem = inst.find_element(
                    By.CSS_SELECTOR, SELECTORS["instance_time"]
                )
                time_text = sb.execute_script(
                    "return arguments[0].textContent.trim();", time_elem
                )
                if not time_text:
                    continue

                date_obj = datetime.strptime(date_text, "%d %B, %Y")
                date = date_obj.strftime("%Y-%m-%d")
                time_obj = datetime.strptime(time_text.lower(), "%I:%M%p")
                time_val = time_obj.strftime("%H:%M")
                datetime_key = f"{date} {time_val}"

                upcoming_performances.append({"date": date, "time": time_val})
                seat_pricing[datetime_key] = []

                link_elem = inst.find_elements(
                    By.CSS_SELECTOR, SELECTORS["instance_link"]
                )
                if link_elem:
                    href = link_elem[0].get_attribute("href")
                    performance_links[href] = datetime_key

                self.custom_logger.info("Collected: %s", datetime_key)

            except Exception as e:
                self.custom_logger.warning("Error parsing performance: %s", e)

        self.custom_logger.info(
            "Total performances: %d | Links: %d",
            len(upcoming_performances),
            len(performance_links),
        )

        capacity_values: list[int] = []
        currency = None
        failed_perfs: list[tuple] = []  # (href, datetime_key)

        # ── First pass ────────────────────────────────────────────────
        for link, datetime_key in performance_links.items():
            full_link = f"https://www.goh.co.uk{link}" if link.startswith("/") else link
            self.custom_logger.info(
                "Opening performance: %s - %s", datetime_key, full_link
            )
            self.safe_get(sb, full_link)
            human_delay(5, 6.5)

            try:
                sb.execute_script(
                    "var el = document.querySelector('.icon-close'); if (el) el.click();"
                )
            except Exception:
                pass
            human_delay(5, 7)

            seats, cap, curr = self._scrape_performance_seats(sb)

            if seats or cap:
                seat_pricing[datetime_key] = seats
                if cap:
                    capacity_values.append(cap)
                if curr and currency is None:
                    currency = curr
                self.custom_logger.info(
                    "Performance %s: %d seats, capacity=%s",
                    datetime_key,
                    len(seats),
                    cap,
                )
            else:
                self.custom_logger.warning(
                    "Performance %s: no data — queued for retry", datetime_key
                )
                failed_perfs.append((link, datetime_key))

        # ── Retry passes ──────────────────────────────────────────────
        _MAX_RETRY_PASSES = 10
        for _retry_pass in range(1, _MAX_RETRY_PASSES + 1):
            if not failed_perfs:
                break

            _cd_min = min(30 + 10 * (_retry_pass - 1), 60)
            _cd_max = min(60 + 15 * (_retry_pass - 1), 120)
            self.custom_logger.info(
                "Performance retry pass %d/%d — %d failed | cooling down %d-%ds",
                _retry_pass,
                _MAX_RETRY_PASSES,
                len(failed_perfs),
                _cd_min,
                _cd_max,
            )
            human_scroll(sb)
            human_delay(_cd_min, _cd_max)

            still_failed = []
            for link, datetime_key in failed_perfs:
                full_link = (
                    f"https://www.goh.co.uk{link}" if link.startswith("/") else link
                )
                self.custom_logger.info(
                    "Retry %d: %s - %s", _retry_pass, datetime_key, full_link
                )
                self.safe_get(sb, full_link)
                human_delay(5, 6.5)

                try:
                    sb.execute_script(
                        "var el = document.querySelector('.icon-close'); if (el) el.click();"
                    )
                except Exception:
                    pass
                human_delay(5, 7)

                seats, cap, curr = self._scrape_performance_seats(sb)

                if seats or cap:
                    seat_pricing[datetime_key] = seats
                    if cap:
                        capacity_values.append(cap)
                    if curr and currency is None:
                        currency = curr
                    self.custom_logger.info(
                        "Retry pass %d success: %s — %d seats",
                        _retry_pass,
                        datetime_key,
                        len(seats),
                    )
                else:
                    still_failed.append((link, datetime_key))
                    self.custom_logger.warning(
                        "Retry pass %d still failed: %s", _retry_pass, datetime_key
                    )

                human_delay(8, 14)

            failed_perfs = still_failed

        if failed_perfs:
            self.custom_logger.warning(
                "%d performance(s) still empty after %d retry passes: %s",
                len(failed_perfs),
                _MAX_RETRY_PASSES,
                [fp[1] for fp in failed_perfs],
            )

        # Sold-out performances have a datetime key but no navigation link.
        # No-seat-map performances were navigated but returned no seats.
        visited_keys = set(performance_links.values())
        sold_out_keys = {k for k in seat_pricing if k not in visited_keys}
        any_seats_found = any(seat_pricing.get(k) for k in visited_keys)

        if visited_keys and not any_seats_found:
            seat_pricing = {}
        else:
            seat_pricing = {
                k: v for k, v in seat_pricing.items() if k in sold_out_keys or v
            }

        for perf in upcoming_performances:
            key = f"{perf['date']} {perf['time']}"
            if key not in seat_pricing:
                seat_pricing[key] = []

        sample_seats = ", ".join(
            s["seat"] for v in list(seat_pricing.values())[:1] for s in v[:5]
        )
        final_capacity = max(capacity_values) if capacity_values else None
        self.custom_logger.info("Total Capacity: %s", final_capacity)
        self.custom_logger.info("Currency: %s", currency)
        self.custom_logger.info("Sample Seats: %s", sample_seats)

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
            "booking_start_date": None,
            "booking_end_date": close_date,
            "upcoming_performances": upcoming_performances,
            "seat_pricing": seat_pricing,
            "capacity": final_capacity,
            "currency": currency or DEFAULT_CURRENCY,
            "is_limited_run": None,
            "scrape_datetime": get_scrape_datetime(),
        }

    def _scrape_shows(self, sb, show_links: list, category: str) -> None:
        """Scrape individual show pages with multi-pass retry (Denver pattern)."""
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
                    human_delay(8, 15)

            pending = still_pending

            if pending and _pass < _MAX_PASSES:
                self.custom_logger.info(
                    "Pass %d complete — %d show(s) still pending. "
                    "Cooling down before pass %d",
                    _pass,
                    len(pending),
                    _pass + 1,
                )
                human_scroll(sb)
                human_delay(60, 120)

        if pending:
            self.custom_logger.warning(
                "%d show(s) could not be scraped after %d passes: %s",
                len(pending),
                _MAX_PASSES,
                pending,
            )

    def extract(self) -> bytes:
        """Open SB session, scrape all shows, populate self.all_data, return JSON bytes."""
        self.all_data = []

        with SB(
            uc=True,
            test=True,
            headless=True,
            browser="chrome",
            locale="en-US",
            chromium_arg="--enable-features=TranslateUI",
        ) as sb:
            self.custom_logger.info(
                "Starting extraction from Belfast Grand Opera House"
            )

            for url in BASE_URLS:
                if not self.safe_get(sb, url):
                    continue

                human_delay(4, 6)
                sb.maximize_window()
                self.accept_cookies(sb)

                category = standardize_category(
                    "drama" if "drama" in url.lower() else "musical"
                )
                self.custom_logger.info("Category: %s", category)

                links = self.get_pagination_links(sb)
                pages = links if links else [(1, sb.get_current_url())]

                for _, link in pages:
                    self.safe_get(sb, link)
                    human_delay(7, 8.5)
                    self.accept_cookies(sb)

                    show_links = self.get_links(sb, SELECTORS["show_links"])

                    if self.local_test:
                        self.custom_logger.info(
                            "LOCAL TEST MODE: Limiting to %s shows", self.show_count
                        )
                        show_links = show_links[: self.show_count]

                    self._scrape_shows(sb, show_links, category)

        return json.dumps(self.all_data, default=str).encode("utf-8")

    def _parse(self, _raw: bytes):
        """Build DataFrame from self.all_data collected during extract()."""
        df = pd.DataFrame(self.all_data)
        self.custom_logger.info("Parsing completed. Extracted %s shows", len(df))
        return df


def main():
    """Example usage of the Belfast Grand Opera House extractor."""
    extractor = BelfastGrandOperaHouseExtractor(
        save_csv_locally=False, csv_incremental_mode=False
    )
    result = extractor.run()
    logger.info(f"Extraction result: {result}")
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
