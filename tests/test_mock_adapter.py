from core.config_loader import Target
from scrapers.plugins.mock_adapter import MockScraper


async def test_mock_scraper_returns_result_under_max_price():
    target = Target(id="t1", adapter="mock", query="widget", max_price=50.0)
    scraper = MockScraper(antibot_config=None)

    results = await scraper.search(target)

    assert len(results) == 1
    assert results[0].price == 49.0
    assert "widget" in results[0].title.lower()


async def test_mock_scraper_defaults_price_without_max_price():
    target = Target(id="t2", adapter="mock", query="gadget")
    scraper = MockScraper(antibot_config=None)

    results = await scraper.search(target)

    assert results[0].price == 50.0
