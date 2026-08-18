from __future__ import annotations

from core.config_loader import Target
from scrapers.base import BaseScraper, ListingResult


class MockScraper(BaseScraper):
    """Deterministic fake adapter used in tests; no network, no browser."""

    async def search(self, target: Target) -> list[ListingResult]:
        price = target.max_price - 1 if target.max_price else 50.0
        return [
            ListingResult(
                product_key=f"mock-{target.id}-1",
                title=f"{target.query} - Mock Result",
                url=f"https://example.com/mock/{target.id}",
                price=price,
                seller="MockStore",
                condition="new",
            )
        ]
