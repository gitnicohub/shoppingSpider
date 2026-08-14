from __future__ import annotations

import html
import logging

from telegram import Bot
from telegram.error import TelegramError

from core.config_loader import Target
from core.database import Listing, NotificationAction

logger = logging.getLogger(__name__)


def format_message(listing: Listing, action: NotificationAction, target: Target) -> str:
    if action == NotificationAction.NEW:
        header = "🔥 <b>NUOVA OFFERTA RILEVATA!</b>"
        reference_price = target.max_price
        reference_label = "Prezzo target"
    else:
        header = "📉 <b>PREZZO SCESO ULTERIORMENTE!</b>"
        reference_price = listing.last_notified_price
        reference_label = "Prezzo precedente"

    price_line = f"💰 <b>Prezzo:</b> {listing.last_price:.2f} €"
    if reference_price is not None:
        price_line += f" ({reference_label}: {reference_price:.2f} €)"

    platform = html.escape(listing.seller or listing.adapter)
    title = html.escape(listing.title)
    url = html.escape(listing.url)
    return (
        f"{header}\n"
        f"📦 <b>Prodotto:</b> {title}\n"
        f"{price_line}\n"
        f"🏪 <b>Piattaforma:</b> {platform}\n"
        f'🔗 <a href="{url}">Vai all\'offerta</a>'
    )


async def send_notification(bot: Bot, chat_id: str, message: str, max_retries: int = 2) -> bool:
    attempt = 0
    while attempt <= max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            return True
        except TelegramError as e:
            attempt += 1
            logger.warning("Telegram send failed (attempt %d/%d): %s", attempt, max_retries, e)
    logger.error("Giving up sending Telegram notification after %d attempts", max_retries + 1)
    return False
