from datetime import datetime, timezone
from unittest.mock import AsyncMock

from telegram.error import TelegramError

from core.config_loader import Target
from core.database import Listing, NotificationAction
from core.notifier import format_message, send_notification


def _listing(**overrides):
    defaults = dict(
        id=1, target_id="t1", adapter="google_shopping", external_id="abc",
        title="Cuffie Bluetooth XYZ", url="https://example.com/item",
        seller="StoreA", condition="new",
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        first_price=79.99, last_price=49.99, last_notified_price=None, notified_count=0,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _target(**overrides):
    defaults = dict(id="t1", adapter="google_shopping", query="cuffie bluetooth", max_price=75.0)
    defaults.update(overrides)
    return Target(**defaults)


def test_format_message_new_offer_includes_target_price():
    message = format_message(_listing(), NotificationAction.NEW, _target())
    assert "NUOVA OFFERTA" in message
    assert "49.99" in message
    assert "75.00" in message
    assert "Cuffie Bluetooth XYZ" in message
    assert "https://example.com/item" in message


def test_format_message_price_drop_includes_previous_notified_price():
    listing = _listing(last_price=44.99, last_notified_price=49.99)
    message = format_message(listing, NotificationAction.PRICE_DROP, _target())
    assert "PREZZO SCESO" in message
    assert "44.99" in message
    assert "49.99" in message


async def test_send_notification_success():
    bot = AsyncMock()
    result = await send_notification(bot, chat_id="123", message="hello")
    assert result is True
    bot.send_message.assert_awaited_once()


async def test_send_notification_retries_then_gives_up():
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramError("boom")
    result = await send_notification(bot, chat_id="123", message="hello", max_retries=2)
    assert result is False
    assert bot.send_message.await_count == 3
