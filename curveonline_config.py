"""Configuration for the Leicester Curve Theatre scraper."""

SITE_ID = "leicester_curve"
BASE_URL = "https://www.curveonline.co.uk/"
RUN_HEADLESS = True
DEFAULT_CURRENCY = "GBP"

PAGES = [
    (f"{BASE_URL}whats-on/?genre-filter=musical", "Musical"),
    (f"{BASE_URL}whats-on/?genre-filter=drama", "Play"),
    (f"{BASE_URL}whats-on/?genre-filter=family", "Musical"),
    (f"{BASE_URL}whats-on/?genre-filter=children-and-young-peoples-theatre", "Musical"),
]

COOKIE_BTN_XPATH = (
    "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']"
)

DEFAULT_THEATRE_DETAILS = {
    "venue": "Curve Theatre",
    "address": "Theatre, Curve, 60 Rutland Street, Leicester, LE1 1SB",
    "city": "Leicester",
    "country": "UK",
}

SELECTORS = {
    "cookie_button": "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']",
    "theatre_address": ".white-wrapper p.AreaAndVenueDetails",
    "address_header_xpath": "//p[contains(@class, 'h4') and contains(text(), 'Address')]",
    "address_paragraph_xpath": "/following-sibling::p",
    "shows_cards": "article.listing__item",
    "shows_link": "article.grid__cell a",
    "title": "header.flush--right h1.major-title",
    "terminal_date": "header.flush--right .show__date",
    "venue_url": "article.listing__item a",
    "year": ".show__time, .show__date",
    "date_blocks": "article.listing__info",
    "booking_url": "a",
    "raw_date_text": ".listing__date time",
    "raw_time_text": ".listing__time time",
    "iframe": "#SpektrixIFrame",
    "seats": "div.SeatingArea img[class*='Seat'], rect.seat",
    "available_seats": "img[class*='Seat']",
}
