from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
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
    assert "StoreA" in message


def test_format_message_price_drop_includes_previous_notified_price():
    listing = _listing(last_price=44.99, last_notified_price=49.99)
    message = format_message(listing, NotificationAction.PRICE_DROP, _target())
    assert "PREZZO SCESO" in message
    assert "44.99" in message
    assert "49.99" in message
    assert "StoreA" in message


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


def test_format_message_falls_back_to_adapter_when_seller_is_none():
    listing = _listing(seller=None)
    message = format_message(listing, NotificationAction.NEW, _target())
    assert "google_shopping" in message
    assert "Piattaforma" in message


def test_format_message_escapes_hostile_title_and_url():
    listing = _listing(
        title="Sony WH-1000XM4 *PROMO* _Nuovo_ [2024]",
        url="https://ex.com/p?a=1&b=(2)",
    )
    message = format_message(listing, NotificationAction.NEW, _target())

    # Raw hostile characters must not appear unescaped in the URL/href.
    assert "a=1&b=(2)" not in message
    assert "a=1&amp;b=(2)" in message

    # Title with Markdown-special characters must be preserved verbatim as text
    # (HTML has no need to escape *, _, [, ] - only &, <, >, " need escaping).
    assert "Sony WH-1000XM4 *PROMO* _Nuovo_ [2024]" in message

    # Structure must use HTML tags, not Markdown syntax.
    assert "<b>" in message
    assert '<a href="https://ex.com/p?a=1&amp;b=(2)">' in message


async def test_send_notification_non_telegram_error_propagates():
    bot = AsyncMock()
    bot.send_message.side_effect = ValueError("unexpected failure")

    with pytest.raises(ValueError):
        await send_notification(bot, chat_id="123", message="hello")
