"""Configuration for Curve Online Theatre scraper."""

SITE_ID = "Curve Online Theatre"
BASE_URL = "https://www.curveonline.co.uk/"
RUN_HEADLESS = True
MAX_RETRIES = 3
RETRY_DELAY = (2, 4)

PAGES = [
    (f"{BASE_URL}whats-on/?genre-filter=musical", "Musical"),
    (f"{BASE_URL}whats-on/?genre-filter=drama", "Play"),
]

COOKIE_BTN_XPATH = (
    "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']"
)

DEFAULT_CURRENCY = "GBP"

PAGE_LOAD_TIMEOUT = 60
IFRAME_WAIT_TIMEOUT = 5
SEAT_WAIT_TIMEOUT = 5

DELAY_BETWEEN_SHOWS = (2, 4)
DELAY_BETWEEN_PERFS = (1, 3)


DEFAULT_THEATRE_DETAILS = {
    "address": "Theatre, Curve, 60 Rutland Street, Leicester, LE1 1SB",
    "venue": "Curve Theatre",
    "city": "Leicester",
    "country": "UK",
}

SELECTORS ={
    "cookie_button": "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']"
    "theatre_address": ".white-wrapper p.AreaAndVenueDetails",
    "address_header_xpath": "//p[contains(@class, 'h4') and contains(text(), 'Address')]",
    "address_paragraph_xpath": "/following-sibling::p",
    "shows_cards": "article.listing__item",
    "title": "h2.media__title",
    "terminal_date": "article.listing__item show__date"
    "venue_url": "article.listing__item a",
    "venue_name": "div.white-wrapper span.AreaName"
    # Mon 13 - Sat 18 Jul 2026 / Sat 4 Jul 2026
    "year": ".show__time, .show__date",
    "date_blocks": "article.listing__info",
    "booking_url": "article.listing__info a",
    "raw_date_text": ".listing__date time",
    "raw_time_text": ".listing__time time",
    "iframe": "SpektrixIFrame",
    "all_seats": "div.SeatingArea img",
    "available_seats": "img[class*='Seat']",
    
}
