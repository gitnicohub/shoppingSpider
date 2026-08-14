from __future__ import annotations

import logging

from core.antibot import jittered_sleep, with_retry
from core.config_loader import AppConfig, Target
from core.database import NotificationAction, mark_notified, process_listing
from core.filters import passes_filters
from core.notifier import format_message, send_notification
from scrapers.base import BaseScraper
from scrapers.plugins.google_shopping import GoogleShoppingScraper
from scrapers.plugins.mock_adapter import MockScraper

logger = logging.getLogger(__name__)

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "google_shopping": GoogleShoppingScraper,
    "mock": MockScraper,
}


async def run_cycle(session_factory, config: AppConfig, targets: list[Target], bot, dry_run: bool = False) -> None:
    for target in targets:
        scraper_cls = SCRAPER_REGISTRY.get(target.adapter)
        if scraper_cls is None:
            logger.error("Unknown adapter '%s' for target '%s', skipping", target.adapter, target.id)
            continue

        scraper = scraper_cls(config.antibot)

        try:
            results = await with_retry(
                lambda: scraper.search(target),
                max_retries=config.antibot.max_retries,
                backoff_base_seconds=config.antibot.backoff_base_seconds,
            )
        except Exception as e:
            logger.warning("Target '%s' failed after retries, skipping this cycle: %s", target.id, e)
            continue

        with session_factory() as session:
            for result in results:
                if not passes_filters(result, target):
                    continue

                renotify_drop_pct = (
                    target.renotify_drop_pct
                    if target.renotify_drop_pct is not None
                    else config.default_renotify_drop_pct
                )
                action, listing = process_listing(session, target.id, target.adapter, result, renotify_drop_pct)

                if action == NotificationAction.NONE:
                    continue

                message = format_message(listing, action, target)
                if dry_run:
                    logger.info("[DRY RUN] Would send notification:\n%s", message)
                    mark_notified(session, listing, listing.last_price)
                    continue

                await send_notification(bot, config.telegram.chat_id, message)
                mark_notified(session, listing, listing.last_price)

        await jittered_sleep(*config.polling.jitter_between_targets_seconds)


async def run_forever(session_factory, config: AppConfig, targets: list[Target], bot, dry_run: bool = False) -> None:
    while True:
        await run_cycle(session_factory, config, targets, bot, dry_run=dry_run)
        await jittered_sleep(config.polling.min_interval_seconds, config.polling.max_interval_seconds)
