from core.config_loader import Target
from core.filters import passes_filters
from scrapers.base import ListingResult


def _target(**overrides):
    defaults = dict(id="t1", adapter="mock", query="widget")
    defaults.update(overrides)
    return Target(**defaults)


def _result(**overrides):
    defaults = dict(product_key="k1", title="Blue Widget Pro", url="https://x", price=50.0, seller="Acme", condition="new")
    defaults.update(overrides)
    return ListingResult(**defaults)


def test_passes_when_no_filters_set():
    assert passes_filters(_result(), _target()) is True


def test_fails_when_price_exceeds_max():
    assert passes_filters(_result(price=100.0), _target(max_price=50.0)) is False


def test_passes_when_price_within_max():
    assert passes_filters(_result(price=40.0), _target(max_price=50.0)) is True


def test_fails_when_include_keyword_missing():
    target = _target(keywords_include=["gaming"])
    assert passes_filters(_result(title="Blue Widget Pro"), target) is False


def test_passes_when_include_keyword_present_case_insensitive():
    target = _target(keywords_include=["WIDGET"])
    assert passes_filters(_result(title="Blue Widget Pro"), target) is True


def test_fails_when_exclude_keyword_present():
    target = _target(keywords_exclude=["ricondizionato"])
    assert passes_filters(_result(title="Widget Ricondizionato"), target) is False


def test_fails_when_seller_mismatch():
    target = _target(seller="OtherStore")
    assert passes_filters(_result(seller="Acme"), target) is False


def test_fails_when_condition_mismatch():
    target = _target(condition="used")
    assert passes_filters(_result(condition="new"), target) is False
