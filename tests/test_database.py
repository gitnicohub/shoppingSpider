import pytest

from core.database import NotificationAction, init_db, mark_notified, process_listing
from scrapers.base import ListingResult


@pytest.fixture
def session_factory(tmp_path):
    db_path = str(tmp_path / "test.db")
    return init_db(db_path)


def _result(price=100.0, key="abc123"):
    return ListingResult(
        product_key=key, title="Test Product", url="https://example.com/p",
        price=price, seller="Store A", condition="new",
    )


def test_new_listing_triggers_new_action(session_factory):
    with session_factory() as session:
        action, listing = process_listing(session, "target1", "mock", _result(), renotify_drop_pct=0.05)
        assert action == NotificationAction.NEW
        assert listing.last_price == 100.0
        assert listing.first_price == 100.0


def test_same_price_never_notifies_twice(session_factory):
    with session_factory() as session:
        action, listing = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        mark_notified(session, listing, 100.0)

        action2, _ = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        assert action2 == NotificationAction.NONE


def test_small_drop_below_threshold_does_not_notify(session_factory):
    with session_factory() as session:
        _, listing = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        mark_notified(session, listing, 100.0)

        action, _ = process_listing(session, "target1", "mock", _result(price=98.0), renotify_drop_pct=0.05)
        assert action == NotificationAction.NONE


def test_significant_drop_triggers_price_drop_notification(session_factory):
    with session_factory() as session:
        _, listing = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        mark_notified(session, listing, 100.0)

        action, listing2 = process_listing(session, "target1", "mock", _result(price=90.0), renotify_drop_pct=0.05)
        assert action == NotificationAction.PRICE_DROP

        mark_notified(session, listing2, 90.0)
        assert listing2.last_notified_price == 90.0
        assert listing2.notified_count == 2


def test_different_targets_are_independent(session_factory):
    with session_factory() as session:
        action_a, _ = process_listing(session, "targetA", "mock", _result(key="same-key"), renotify_drop_pct=0.05)
        action_b, _ = process_listing(session, "targetB", "mock", _result(key="same-key"), renotify_drop_pct=0.05)
        assert action_a == NotificationAction.NEW
        assert action_b == NotificationAction.NEW
