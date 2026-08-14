from unittest.mock import AsyncMock

import pytest

from core.antibot import RetryableError, jittered_sleep, pick_proxy, pick_user_agent, with_retry


def test_pick_user_agent_returns_from_list():
    agents = ["UA1", "UA2"]
    assert pick_user_agent(agents) in agents


def test_pick_user_agent_empty_raises():
    with pytest.raises(ValueError):
        pick_user_agent([])


def test_pick_proxy_empty_returns_none():
    assert pick_proxy([]) is None


def test_pick_proxy_returns_from_list():
    proxies = ["http://p1", "http://p2"]
    assert pick_proxy(proxies) in proxies


async def test_jittered_sleep_calls_asyncio_sleep_within_range(monkeypatch):
    captured = {}

    async def fake_sleep(seconds):
        captured["seconds"] = seconds

    monkeypatch.setattr("core.antibot.asyncio.sleep", fake_sleep)
    await jittered_sleep(1.0, 2.0)
    assert 1.0 <= captured["seconds"] <= 2.0


async def test_with_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr("core.antibot.asyncio.sleep", AsyncMock())
    calls = {"count": 0}

    async def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RetryableError("boom")
        return "ok"

    result = await with_retry(flaky, max_retries=3, backoff_base_seconds=0.01)
    assert result == "ok"
    assert calls["count"] == 3


async def test_with_retry_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("core.antibot.asyncio.sleep", AsyncMock())

    async def always_fails():
        raise RetryableError("nope")

    with pytest.raises(RetryableError):
        await with_retry(always_fails, max_retries=2, backoff_base_seconds=0.01)
