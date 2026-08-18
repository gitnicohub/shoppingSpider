from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Raised by scrapers on 403/429/timeout to trigger retry with backoff."""


def pick_user_agent(user_agents: list[str]) -> str:
    if not user_agents:
        raise ValueError("user_agents list is empty")
    return random.choice(user_agents)


def pick_proxy(proxies: list[str]) -> str | None:
    if not proxies:
        return None
    return random.choice(proxies)


async def jittered_sleep(low: float, high: float) -> None:
    if low > high:
        raise ValueError("low must be <= high")
    await asyncio.sleep(random.uniform(low, high))


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    max_retries: int,
    backoff_base_seconds: float,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except RetryableError as e:
            attempt += 1
            if attempt > max_retries:
                logger.warning("Exhausted %d retries: %s", max_retries, e)
                raise
            delay = backoff_base_seconds * (2 ** (attempt - 1)) + random.uniform(0, backoff_base_seconds)
            logger.warning(
                "Retryable error (attempt %d/%d), backing off %.1fs: %s",
                attempt, max_retries, delay, e,
            )
            await asyncio.sleep(delay)
