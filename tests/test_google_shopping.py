from pathlib import Path

import pytest

from scrapers.plugins.google_shopping import parse_listings

SYNTHETIC_HTML = """
<html><body>
<div class="sh-dgr__grid-result">
  <h3>Cuffie Bluetooth XYZ Pro</h3>
  <a href="/shopping/product/1"></a>
  <span aria-hidden="true">49,99&nbsp;€</span>
  <div class="aULzUe">NegozioA</div>
</div>
<div class="sh-dgr__grid-result">
  <h3>Cuffie Bluetooth ABC Lite</h3>
  <a href="https://negoziob.it/prodotto/2"></a>
  <span aria-hidden="true">1.234,50&nbsp;€</span>
  <div class="aULzUe">NegozioB</div>
</div>
</body></html>
"""

NO_PRICE_HTML = """
<div class="sh-dgr__grid-result">
  <h3>Prodotto senza prezzo</h3>
  <a href="/x"></a>
</div>
"""

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_shopping_sample.html"


def test_parse_listings_extracts_title_price_seller_url():
    listings = parse_listings(SYNTHETIC_HTML)

    assert len(listings) == 2

    first = listings[0]
    assert first.title == "Cuffie Bluetooth XYZ Pro"
    assert first.price == 49.99
    assert first.seller == "NegozioA"
    assert first.url == "https://www.google.com/shopping/product/1"

    second = listings[1]
    assert second.title == "Cuffie Bluetooth ABC Lite"
    assert second.price == 1234.50
    assert second.url == "https://negoziob.it/prodotto/2"


def test_parse_listings_skips_cards_without_price():
    assert parse_listings(NO_PRICE_HTML) == []


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="Real fixture not captured yet - see Task 7 Step 6 in the implementation plan",
)
def test_parse_listings_against_real_fixture():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    listings = parse_listings(html)
    assert len(listings) > 0
    for listing in listings:
        assert listing.title
        assert listing.price > 0
