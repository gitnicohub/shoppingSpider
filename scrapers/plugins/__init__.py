from __future__ import annotations

from scrapers.base import BaseScraper
from scrapers.plugins.google_shopping import GoogleShoppingScraper
from scrapers.plugins.mock_adapter import MockScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "google_shopping": GoogleShoppingScraper,
    "mock": MockScraper,
}
