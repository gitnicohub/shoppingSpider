from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from telegram import Bot

from core.config_loader import ConfigError, load_config
from core.database import init_db
from core.engine import run_cycle, run_forever


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Universal offer/product crawler with Telegram notifications"
    )
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Log notifications instead of sending them")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    parser.add_argument("--targets", default="config/targets.json", help="Path to targets.json")
    return parser


async def _run(args: argparse.Namespace) -> None:
    config, targets = load_config(Path(args.config), Path(args.targets))
    session_factory = init_db(config.database.path)
    bot = Bot(token=config.telegram.bot_token)

    if args.once:
        await run_cycle(session_factory, config, targets, bot, dry_run=args.dry_run)
    else:
        await run_forever(session_factory, config, targets, bot, dry_run=args.dry_run)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()

    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except ConfigError as e:
        logging.getLogger(__name__).error("Configuration error: %s", e)
        raise SystemExit(1) from e
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Interrupted, shutting down")


if __name__ == "__main__":
    main()
