"""Leicester Curve extractor implementation using the framework."""
import json
import random
import re
import sys
import time
from datetime import date, datetime

import pandas as pd
from dateutil import parser
from selenium.webdriver.common.by import By
from seleniumbase import SB

from utils.base_extractor import BaseExtractor
from utils.logger import setup_logger
from utils.scraping_helpers import (
    convert_to_24hr,
    extract_postcode,
    format_datetime_key,
    get_city_country_uk,
    get_currency_from_price,
    get_scrape_datetime,
    human_delay,
    human_scroll,
    normalize_country,
    parse_booking_dates,
    standardize_category,
)

from .leicester_curve_config import (  # COOKIE_BTN_XPATH,
    DEFAULT_CURRENCY,
    DEFAULT_THEATRE_DETAILS,
    PAGES,
    SELECTORS,
)

logger = setup_logger(__name__, log_to_file=False)


class LeicesterCurveExtractor(BaseExtractor):
    """Extractor for the Leicester Curve website."""

    def __init__(self, local_test=False, show_count=2, **kwargs):
        super().__init__(
            site_id="leicester_curve",
            log_to_file=False,
            log_to_terminal=True,
            local_test=local_test,
            show_count=show_count,
            **kwargs,
        )
        self.all_data = []

    def safe_get(self, sb, url, wait=10):
        try:
            # self.custom_logger.info("Loading URL: %s", url)
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

    def _parse_date(self, text: str) -> date | None:
        try:
            dt = parser.parse(text, dayfirst=True, fuzzy=True)
            if dt.date() < date.today():
                dt = dt.replace(year=dt.year + 1)
            return dt.strftime("%Y-%m-%d")
        except Exception as e:
            self.custom_logger.error(f"_parse_date failed for '{text}': {e}")
            return None

    def get_show_links(self, sb):
        elements = sb.find_elements(By.CSS_SELECTOR, SELECTORS["shows_link"])
        return [e.get_attribute("href") for e in elements if e.get_attribute("href")]

    def _get_show_title(self, sb) -> str | None:
        """Extract show title."""
        try:
            return sb.get_text(SELECTORS["title"]).strip() or None
        except Exception:
            return None

    def _get_terminal_dates(
        self, sb
    ) -> str | None:  # Fixed type hinting hint to match output tuple
        """Extract show header dates."""
        try:
            # Mon 13 - Sat 18 Jul 2026
            terminal_date = sb.get_text(SELECTORS["terminal_date"])
            return terminal_date.strip() if terminal_date else None
        except Exception as e:
            self.custom_logger.debug(
                f" terminal date extraction failed: {e}", "warning"
            )
            return None

    def _get_theatre_address(self, sb) -> dict:
        """Extract theatre address."""
        data = {}
        try:
            address = sb.find_element(SELECTORS["theatre_address"]).text.replace(
                "\n", ""
            )
            if address:
                # Theatre, Curve, 60 Rutland Street, Leicester, LE1 1SB
                data["address"] = address
                parts = address.split(",")
                curve = parts[1] if len(parts) > 1 else ""
                theatre = parts[0]

                venue_string = f"{curve} {theatre}"
                data["venue"] = (
                    venue_string.strip()
                    if "curve" in address.lower()
                    else "Studio Theatre"
                )

                postcode = extract_postcode(address, region="UK")
                if postcode:
                    city, country = get_city_country_uk(postcode)
                    data["city"] = city
                    data["country"] = country
            return data

        except Exception as e:
            self.custom_logger.info(
                f" Address extraction failed, fallback to default: {e}", "warning"
            )
            return DEFAULT_THEATRE_DETAILS

    def _extract_performances(self, sb) -> list[dict]:
        """Parses performance instances directly from Curve's single or continuous date markers."""

        performances = []
        seen_urls = set()

        try:
            date_blocks = sb.find_elements(By.CSS_SELECTOR, SELECTORS["date_blocks"])
            self.custom_logger.info(f" Found {len(date_blocks)} performance dates")

            for block in date_blocks:
                try:
                    booking_url = block.find_element(
                        By.TAG_NAME, SELECTORS["booking_url"]
                    ).get_attribute("href")
                    # Deduplicate based on unique performance booking URL
                    if booking_url in seen_urls:
                        continue

                    raw_date_text = (
                        block.find_element(By.CSS_SELECTOR, SELECTORS["raw_date_text"])
                        .get_attribute("textContent")
                        .strip()
                    )
                    raw_time_text = (
                        block.find_element(By.CSS_SELECTOR, SELECTORS["raw_time_text"])
                        .get_attribute("textContent")
                        .strip()
                    )
                    if not raw_date_text or not raw_time_text:
                        continue

                    year = str(datetime.now().year)
                    date_string = f"{raw_date_text} {year} {raw_time_text}"

                    date_ymd = self._parse_date(date_string)
                    time_hm = convert_to_24hr(raw_time_text)

                    performances.append(
                        {
                            "date": date_ymd,
                            "time": time_hm,
                            "booking_url": ("" if "tel" in booking_url else booking_url)
                            # "booking_url": booking_url
                        }
                    )
                    seen_urls.add(booking_url)

                except Exception as inner_e:
                    self.custom_logger.debug(
                        f"Date block parsing failed due to inner error: {inner_e}"
                    )
                    continue

        except Exception as e:
            self.custom_logger.debug(f" Error extracting performances: {e}")
        return performances

    def extract_seats(self, sb) -> tuple:
        """Extracts seats and pricing from the currently open SVG modal."""

        max_capacity = None
        currency = None

        all_seats = {}

        try:
            address = sb.find_element(SELECTORS["theatre_address"]).text.replace(
                "\n", ""
            )
        except Exception:
            address = DEFAULT_THEATRE_DETAILS["address"]

        try:
            sb.wait_for_element_present(SELECTORS["seats"], timeout=12)
            seats = sb.find_elements(By.CSS_SELECTOR, SELECTORS["seats"])
            self.custom_logger.info(f" Found {len(seats)} unique seats. ")

            for seat in seats:
                tooltip = (
                    seat.get_attribute("tooltip") or seat.get_attribute("title") or ""
                )

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

                style = seat.get_attribute("style") or ""
                top_match = re.search(r"top:\s*([\d.]+)%", style)
                section = (
                    "STALLS"
                    if top_match and float(top_match.group(1)) < 59
                    else "CIRCLE"
                )

                if "curve" in address.lower():
                    seat_id = f"{section} {seat_id}"
                else:
                    seat_id = f"STUDIO {seat_id}"

                all_seats[seat_id] = {"seat": seat_id, "ticket_price": ticket_price}

        except Exception as e:
            self.custom_logger.debug(f"Seat canvas extraction subloop failure: {e}")

        seat_list = list(all_seats.values())
        self.custom_logger.info(
            f" Total capacity: {max_capacity} seats ({len(seat_list)} priced)"
        )
        return seat_list, currency, max_capacity

    def extract_seat_metrics(self, sb, performances):  # Fixed: Indented inside class
        """Extracts seats and pricing from internal ticket frame configurations."""

        venue_details = {}
        venue_extracted = False
        seat_pricing = {}

        capacity = None
        currency = None
        encountered_no_seatmap = False

        for i, perf in enumerate(performances, start=1):
            key = format_datetime_key(perf["date"], perf["time"])
            if not key:
                continue

            self.custom_logger.info(
                f" [{i}/{len(performances)}] Seats for {perf['date']} {perf['time']}"
            )

            # Confirm if sold out / Performance has no digital booking URL (likely telephone booking)."
            if not self.safe_get(sb, perf["booking_url"]):
                self.custom_logger.info(
                    f"Performance {key} is sold out or seatmap is unavailable."
                )
                seat_pricing[key] = []
                continue

            try:
                self.safe_get(sb, perf["booking_url"])
                human_delay(4, 5.5)

                sb.wait_for_ready_state_complete()
                if sb.is_element_present(SELECTORS["iframe"]):
                    sb.switch_to_frame(SELECTORS["iframe"])

                    # --- SINGLE-PASS ADDRESS EXTRACTION ---
                    if not venue_extracted:
                        venue_details = self._get_theatre_address(sb)
                        venue_extracted = True
                    # ------------------------------------------------

                    seat_list, perf_currency, perf_capacity = self.extract_seats(sb)
                    if seat_list:
                        seat_pricing[key] = seat_list
                        currency = perf_currency
                        capacity = perf_capacity
                    self.custom_logger.info(
                        f" Seats: {len(seat_list)} | Capacity: {capacity} | Currency: {currency}"
                    )

                else:
                    seat_pricing[key] = []
                    encountered_no_seatmap = True
                    self.custom_logger.info(
                        f" No seat map available for {perf['date']} {perf['time']}"
                    )

            except Exception as e:
                seat_pricing[key] = []
                encountered_no_seatmap = True
                self.custom_logger.warning(f" Seat extraction error: {e}")
                perf["capacity"] = None
            finally:
                try:
                    sb.switch_to.default_content()
                except Exception:
                    pass

            human_delay(5, 7)

        if encountered_no_seatmap and all(
            len(seat_list) == 0 for seat_list in seat_pricing.values()
        ):
            self.custom_logger.info(
                " All performances lack a seat map layout. Resetting seat_pricing = {}"
            )
            seat_pricing = {}

        self.custom_logger.info(" Seat extraction flow processed")
        return seat_pricing, currency, capacity, venue_details

    def _scrape_one_show(self, sb, show_url: str, category: str) -> dict | None:
        """Scrape a single show page end-to-end.

        Returns a completed row dict on success, or None if the show page
        did not render (bot challenge, timeout) — the caller retries.
        """

        if not self.safe_get(sb, show_url):
            return None

        title = self._get_show_title(sb)
        if not title:
            self.custom_logger.warning("No title found for: %s", show_url)

        venue_url = sb.get_current_url()
        self.custom_logger.info("venue_url: %s", venue_url)

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
        self.custom_logger.info("Terminal: %s", terminal_date)

        self.custom_logger.info("Open Date: %s", open_date)
        self.custom_logger.info("Close Date: %s", close_date)
        self.custom_logger.info("-" * 50)

        # sb.execute_script("document.querySelector('a[href*=\"/book/\"]').click();")

        human_delay(10, 12.5)
        human_scroll(sb)
        time.sleep(3)

        performances = self._extract_performances(sb)
        if not performances:
            self.custom_logger.warning(
                f"  No performances found for '{title}', skipping"
            )
            return None

        sorted_dates = sorted([p["date"] for p in performances])
        if not open_date:  # or open_date > close_date
            open_date = sorted_dates[0]

        if not close_date:
            close_date = sorted_dates[-1]

        if open_date > close_date:
            self.custom_logger.warning(
                "  Open date %s is after close date %s. Adjusting open date to performance.",
            )
            open_date = sorted_dates[0]

        seat_pricing, currency, capacity, venue_details = self.extract_seat_metrics(
            sb, performances
        )

        venue_name = venue_details["venue"]
        address = venue_details["address"]
        city = venue_details["city"]
        country = normalize_country(venue_details["country"])

        self.custom_logger.info(
            "Performances: %d | Seat keys: %d",
            len(performances),
            len(seat_pricing),
        )
        self.custom_logger.info("Venue: %s", venue_name)
        self.custom_logger.info("Address: %s", address)
        self.custom_logger.info("City: %s", city)
        self.custom_logger.info("Country: %s", country)
        self.custom_logger.info("Capacity: %s", capacity)
        self.custom_logger.info("Currency: %s", currency)

        return {
            "title": title,
            "category": standardize_category(category),
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
            "scrape_datetime": get_scrape_datetime(),  # datetime.now().strftime("%Y-%m-%d %H:%M"),
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
        seen_links = set()

        with SB(
            uc=True,
            test=True,
            headless=True,
            browser="chrome",
            locale="en-US",
            chromium_arg="--enable-features=TranslateUI",
        ) as sb:
            self.custom_logger.info("Starting extraction from Leicester Curve")

            for i, (url, category) in enumerate(PAGES):
                self.custom_logger.info(f"[Listing] {category}: {url}")
                if not self.safe_get(sb, url):
                    continue

                human_delay(4, 6)
                sb.maximize_window()
                self.accept_cookies(sb)

                show_links = self.get_show_links(sb)

                unique_links = []
                for link in show_links:
                    if link not in seen_links:
                        seen_links.add(link)
                        unique_links.append(link)

                show_links = unique_links

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
    """Example usage of the Leicester Curve extractor."""
    extractor = LeicesterCurveExtractor(
        save_csv_locally=False, csv_incremental_mode=False
    )
    result = extractor.run()
    logger.info(f"Extraction result: {result}")
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
