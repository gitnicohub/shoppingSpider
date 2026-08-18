from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(Exception):
    pass


class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str


class PollingConfig(BaseModel):
    min_interval_seconds: int = 1800
    max_interval_seconds: int = 3600
    jitter_between_targets_seconds: tuple[int, int] = (5, 20)


class AntibotConfig(BaseModel):
    user_agents: list[str] = Field(
        default_factory=lambda: [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]
    )
    proxies: list[str] = Field(default_factory=list)
    max_retries: int = 3
    backoff_base_seconds: float = 5.0


class DatabaseConfig(BaseModel):
    path: str = "data/crawler.db"


class AppConfig(BaseModel):
    telegram: TelegramConfig
    polling: PollingConfig = PollingConfig()
    antibot: AntibotConfig = AntibotConfig()
    database: DatabaseConfig = DatabaseConfig()
    concurrency: int = 1
    default_renotify_drop_pct: float = 0.05


class Target(BaseModel):
    id: str
    adapter: str
    query: str
    max_price: float | None = None
    keywords_include: list[str] = Field(default_factory=list)
    keywords_exclude: list[str] = Field(default_factory=list)
    seller: str | None = None
    condition: str | None = None
    renotify_drop_pct: float | None = None


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env_vars(raw_text: str) -> str:
    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ConfigError(
                f"Environment variable '{var_name}' referenced in config but not set"
            )
        return value

    return _ENV_VAR_PATTERN.sub(replace, raw_text)


def _format_validation_error(e: ValidationError) -> str:
    """Format a pydantic ValidationError without echoing the (possibly secret-bearing) input.

    ValidationError's default __str__ embeds the full input value that failed
    validation, which can leak secrets (e.g. a valid bot_token alongside an
    invalid chat_id). We build the message from loc/msg only.
    """
    parts = []
    for err in e.errors(include_url=False):
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    return "; ".join(parts)


def load_config(config_path: Path, targets_path: Path) -> tuple[AppConfig, list[Target]]:
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if not targets_path.exists():
        raise ConfigError(f"Targets file not found: {targets_path}")

    raw_yaml = _expand_env_vars(config_path.read_text(encoding="utf-8"))
    try:
        config_dict = yaml.safe_load(raw_yaml) or {}
        app_config = AppConfig(**config_dict)
    except ValidationError as e:
        raise ConfigError(f"Invalid config.yaml: {_format_validation_error(e)}") from e
    except (yaml.YAMLError, TypeError) as e:
        raise ConfigError(f"Invalid config.yaml: {e}") from e

    try:
        targets_data = json.loads(targets_path.read_text(encoding="utf-8"))
        targets = [Target(**t) for t in targets_data]
    except ValidationError as e:
        raise ConfigError(f"Invalid targets.json: {_format_validation_error(e)}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid targets.json: {e}") from e

    if not targets:
        raise ConfigError("targets.json must contain at least one target")

    return app_config, targets
