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


def test_crash_recovery_without_notification(session_factory):
    """
    Crash-recovery edge case: listing exists but was never notified.
    Simulates process crash between process_listing() and mark_notified().
    Next sighting must still return NEW, not NONE forever.
    """
    with session_factory() as session:
        action1, listing1 = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        assert action1 == NotificationAction.NEW
        # Deliberately do NOT call mark_notified() — simulating crash

        # Next sighting with same product
        action2, listing2 = process_listing(session, "target1", "mock", _result(price=100.0), renotify_drop_pct=0.05)
        # Since last_notified_price is still None, should still be NEW
        assert action2 == NotificationAction.NEW
        assert listing2.last_notified_price is None


def test_zero_price_notified_does_not_crash(session_factory):
    """
    Division-by-zero edge case: listing notified at price 0.0 (e.g., free/giveaway).
    Next sighting must not raise ZeroDivisionError and should return NONE.
    """
    with session_factory() as session:
        _, listing = process_listing(session, "target1", "mock", _result(price=0.0), renotify_drop_pct=0.05)
        mark_notified(session, listing, 0.0)
        assert listing.last_notified_price == 0.0

        # Next sighting with positive price — must not crash
        action, _ = process_listing(session, "target1", "mock", _result(price=10.0), renotify_drop_pct=0.05)
        # With last_notified_price=0, percentage drop is undefined, so return NONE
        assert action == NotificationAction.NONE
