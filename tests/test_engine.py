from unittest.mock import AsyncMock

import pytest

from core.config_loader import AppConfig, TelegramConfig, Target
from core.database import init_db
from core.engine import run_cycle


@pytest.fixture
def config():
    return AppConfig(telegram=TelegramConfig(bot_token="x", chat_id="123"))


@pytest.fixture
def targets():
    return [Target(id="t1", adapter="mock", query="widget", max_price=50.0)]


async def test_run_cycle_sends_notification_for_new_listing(tmp_path, config, targets, monkeypatch):
    monkeypatch.setattr("core.engine.jittered_sleep", AsyncMock())
    session_factory = init_db(str(tmp_path / "test.db"))
    bot = AsyncMock()

    await run_cycle(session_factory, config, targets, bot)

    bot.send_message.assert_awaited_once()


async def test_run_cycle_does_not_renotify_same_price(tmp_path, config, targets, monkeypatch):
    monkeypatch.setattr("core.engine.jittered_sleep", AsyncMock())
    session_factory = init_db(str(tmp_path / "test.db"))
    bot = AsyncMock()

    await run_cycle(session_factory, config, targets, bot)
    bot.send_message.reset_mock()
    await run_cycle(session_factory, config, targets, bot)

    bot.send_message.assert_not_awaited()


async def test_run_cycle_dry_run_does_not_call_bot(tmp_path, config, targets, monkeypatch):
    monkeypatch.setattr("core.engine.jittered_sleep", AsyncMock())
    session_factory = init_db(str(tmp_path / "test.db"))
    bot = AsyncMock()

    await run_cycle(session_factory, config, targets, bot, dry_run=True)

    bot.send_message.assert_not_awaited()


async def test_run_cycle_skips_unknown_adapter_without_raising(tmp_path, config, monkeypatch):
    monkeypatch.setattr("core.engine.jittered_sleep", AsyncMock())
    session_factory = init_db(str(tmp_path / "test.db"))
    bot = AsyncMock()
    bad_targets = [Target(id="t1", adapter="does_not_exist", query="widget")]

    await run_cycle(session_factory, config, bad_targets, bot)

    bot.send_message.assert_not_awaited()
