from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from core.antibot import RetryableError, pick_proxy, pick_user_agent
from core.config_loader import AntibotConfig, Target
from scrapers.base import BaseScraper, ListingResult

logger = logging.getLogger(__name__)

SEARCH_URL_TEMPLATE = "https://www.google.com/search?tbm=shop&q={query}"
_PRICE_PATTERN = re.compile(r"[\d.,]+")


def _parse_price(raw_price: str) -> float | None:
    match = _PRICE_PATTERN.search(raw_price.replace("\xa0", " "))
    if not match:
        return None
    raw = match.group(0)
    normalized = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return float(normalized)
    except ValueError:
        return None


def parse_listings(html: str) -> list[ListingResult]:
    """Parse a Google Shopping results page into ListingResult objects.

    Google Shopping's DOM structure is undocumented and changes over time.
    These selectors match the sample captured for this project (see
    tests/test_google_shopping.py); recapture a fresh fixture and adjust
    the selectors below if live results stop parsing.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: list[ListingResult] = []

    for card in soup.select("div.sh-dgr__grid-result, div.sh-dlr__list-result"):
        title_el = card.select_one("h3, h4")
        price_el = card.select_one("span[aria-hidden='true']")
        seller_el = card.select_one("div.aULzUe, div.IuHnof")
        link_el = card.select_one("a")

        if title_el is None or price_el is None:
            continue

        price = _parse_price(price_el.get_text())
        if price is None:
            continue

        title = title_el.get_text(strip=True)
        seller = seller_el.get_text(strip=True) if seller_el else None
        url = link_el["href"] if link_el and link_el.has_attr("href") else ""
        if url.startswith("/"):
            url = f"https://www.google.com{url}"

        product_key = f"{title}|{seller or ''}".lower()

        listings.append(
            ListingResult(
                product_key=product_key,
                title=title,
                url=url,
                price=price,
                seller=seller,
                condition=None,
            )
        )

    return listings


class GoogleShoppingScraper(BaseScraper):
    async def search(self, target: Target) -> list[ListingResult]:
        antibot_config: AntibotConfig = self.antibot_config
        url = SEARCH_URL_TEMPLATE.format(query=target.query.replace(" ", "+"))
        user_agent = pick_user_agent(antibot_config.user_agents)
        proxy_url = pick_proxy(antibot_config.proxies)

        launch_kwargs = {}
        if proxy_url:
            launch_kwargs["proxy"] = {"server": proxy_url}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, **launch_kwargs)
            try:
                context = await browser.new_context(user_agent=user_agent)
                page = await context.new_page()
                try:
                    response = await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError as e:
                    raise RetryableError(f"Timeout loading {url}") from e

                if response is not None and response.status in (403, 429):
                    raise RetryableError(
                        f"Blocked with HTTP {response.status} for query '{target.query}'"
                    )

                html = await page.content()
            finally:
                await browser.close()

        return parse_listings(html)
