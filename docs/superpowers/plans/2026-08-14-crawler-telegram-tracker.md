# Crawler/Tracker con notifiche Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI/background worker that polls Google Shopping (via a plugin-style scraper adapter), deduplicates results against a local SQLite DB, and sends Telegram notifications for new offers and significant price drops.

**Architecture:** A sequential asyncio loop (`core/engine.py`) iterates configured targets one at a time, delegates fetching to a pluggable `BaseScraper` adapter (`google_shopping` for real use, `mock` for tests), passes results through a dedup/price-drop decision function backed by SQLAlchemy/SQLite, and sends any resulting notification via `python-telegram-bot`. Config (`config.yaml` + `targets.json`) is validated with pydantic at startup.

**Tech Stack:** Python 3.11+, Playwright (async) + BeautifulSoup4 for scraping, SQLAlchemy 2.0 + SQLite for persistence, pydantic v2 for config validation, python-telegram-bot v21+ for notifications, python-dotenv for secrets, pytest + pytest-asyncio for tests.

## Global Constraints

- Python 3.11+ only.
- MVP implements exactly one real scraper adapter: Google Shopping. The architecture must support adding more via the `scrapers/plugins/` registry without touching `core/`.
- Target processing is strictly sequential (one target at a time, `concurrency: 1`) — no parallel scraping in this iteration.
- A listing is never notified twice for the same price. A new notification for an already-seen listing fires only when the price has dropped by at least `renotify_drop_pct` (default 5%, per-target override allowed) relative to the last *notified* price, not the historical minimum.
- A scraper failure (403/429/timeout/parse error) on one target must never crash the process or stop other targets from being checked; it is logged and skipped for that cycle.
- Telegram message format must match the template in the spec (emoji headers, price vs. reference price, platform, markdown link).
- Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) come from environment variables (`.env`), never hardcoded or committed.
- No web dashboard/UI — CLI + Telegram only.

---

### Task 1: Project scaffolding + config loader

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config/config.yaml`
- Create: `config/targets.json`
- Create: `core/__init__.py`, `scrapers/__init__.py`, `scrapers/plugins/__init__.py`, `tests/__init__.py`, `tests/fixtures/.gitkeep`
- Create: `core/config_loader.py`
- Test: `tests/test_config_loader.py`

**Interfaces:**
- Produces: `core.config_loader.TelegramConfig`, `PollingConfig`, `AntibotConfig`, `DatabaseConfig`, `AppConfig` (pydantic `BaseModel`s), `Target` (pydantic `BaseModel`), `ConfigError(Exception)`, `load_config(config_path: Path, targets_path: Path) -> tuple[AppConfig, list[Target]]`.

- [ ] **Step 1: Create project scaffolding files**

`requirements.txt`:
```
playwright>=1.40
beautifulsoup4>=4.12
sqlalchemy>=2.0
pydantic>=2.0
python-telegram-bot>=21.0
python-dotenv>=1.0
pyyaml>=6.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
```

`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
venv/
.env
data/*.db
.pytest_cache/
```

`.env.example`:
```
TELEGRAM_BOT_TOKEN=123456789:AAExampleTokenReplaceWithReal
TELEGRAM_CHAT_ID=123456789
```

`config/config.yaml`:
```yaml
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"

polling:
  min_interval_seconds: 1800
  max_interval_seconds: 3600
  jitter_between_targets_seconds: [5, 20]

antibot:
  proxies: []
  max_retries: 3
  backoff_base_seconds: 5

database:
  path: "data/crawler.db"

concurrency: 1
default_renotify_drop_pct: 0.05
```

`config/targets.json`:
```json
[
  {
    "id": "esempio-cuffie",
    "adapter": "google_shopping",
    "query": "cuffie bluetooth noise cancelling",
    "max_price": 80.0,
    "keywords_include": ["bluetooth"],
    "keywords_exclude": ["ricondizionato"],
    "renotify_drop_pct": 0.05
  }
]
```

Create empty `core/__init__.py`, `scrapers/__init__.py`, `scrapers/plugins/__init__.py`, `tests/__init__.py`, and `tests/fixtures/.gitkeep` (empty files, just to make the packages/dirs exist).

- [ ] **Step 2: Write the failing test for config_loader**

`tests/test_config_loader.py`:
```python
import json
from pathlib import Path

import pytest

from core.config_loader import ConfigError, load_config

CONFIG_YAML = """
telegram:
  bot_token: "${TEST_BOT_TOKEN}"
  chat_id: "${TEST_CHAT_ID}"
polling:
  min_interval_seconds: 60
  max_interval_seconds: 120
"""

TARGETS_JSON = json.dumps(
    [{"id": "t1", "adapter": "mock", "query": "test product", "max_price": 100.0}]
)


def _write_files(tmp_path: Path, config_text: str = CONFIG_YAML, targets_text: str = TARGETS_JSON):
    config_path = tmp_path / "config.yaml"
    targets_path = tmp_path / "targets.json"
    config_path.write_text(config_text, encoding="utf-8")
    targets_path.write_text(targets_text, encoding="utf-8")
    return config_path, targets_path


def test_load_config_success(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    config_path, targets_path = _write_files(tmp_path)

    app_config, targets = load_config(config_path, targets_path)

    assert app_config.telegram.bot_token == "123:abc"
    assert app_config.telegram.chat_id == "999"
    assert app_config.polling.min_interval_seconds == 60
    assert len(targets) == 1
    assert targets[0].id == "t1"
    assert targets[0].max_price == 100.0


def test_load_config_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    config_path, targets_path = _write_files(tmp_path)

    with pytest.raises(ConfigError, match="TEST_BOT_TOKEN"):
        load_config(config_path, targets_path)


def test_load_config_empty_targets_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    config_path, targets_path = _write_files(tmp_path, targets_text="[]")

    with pytest.raises(ConfigError, match="at least one target"):
        load_config(config_path, targets_path)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -r requirements-dev.txt && pytest tests/test_config_loader.py -v`
Expected: FAIL/ERROR with "No module named 'core.config_loader'" (or ImportError).

- [ ] **Step 4: Implement `core/config_loader.py`**

```python
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
        raise ConfigError(f"Invalid config.yaml: {e}") from e

    try:
        targets_data = json.loads(targets_path.read_text(encoding="utf-8"))
        targets = [Target(**t) for t in targets_data]
    except (ValidationError, json.JSONDecodeError) as e:
        raise ConfigError(f"Invalid targets.json: {e}") from e

    if not targets:
        raise ConfigError("targets.json must contain at least one target")

    return app_config, targets
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config_loader.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini .gitignore .env.example \
  config/config.yaml config/targets.json core/__init__.py scrapers/__init__.py \
  scrapers/plugins/__init__.py tests/__init__.py tests/fixtures/.gitkeep \
  core/config_loader.py tests/test_config_loader.py
git commit -m "feat: add project scaffolding and config loader"
```

---

### Task 2: Scraper base interface + filters

**Files:**
- Create: `scrapers/base.py`
- Create: `core/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `core.config_loader.Target`
- Produces: `scrapers.base.ListingResult` (dataclass: `product_key: str, title: str, url: str, price: float, seller: str | None = None, condition: str | None = None`), `scrapers.base.BaseScraper` (ABC with `__init__(self, antibot_config)` and `async def search(self, target: Target) -> list[ListingResult]`), `core.filters.passes_filters(result: ListingResult, target: Target) -> bool`.

- [ ] **Step 1: Implement `scrapers/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.config_loader import Target


@dataclass
class ListingResult:
    product_key: str
    title: str
    url: str
    price: float
    seller: str | None = None
    condition: str | None = None


class BaseScraper(ABC):
    def __init__(self, antibot_config) -> None:
        self.antibot_config = antibot_config

    @abstractmethod
    async def search(self, target: Target) -> list[ListingResult]:
        raise NotImplementedError
```

- [ ] **Step 2: Write the failing test for filters**

`tests/test_filters.py`:
```python
from core.config_loader import Target
from core.filters import passes_filters
from scrapers.base import ListingResult


def _target(**overrides):
    defaults = dict(id="t1", adapter="mock", query="widget")
    defaults.update(overrides)
    return Target(**defaults)


def _result(**overrides):
    defaults = dict(product_key="k1", title="Blue Widget Pro", url="https://x", price=50.0, seller="Acme", condition="new")
    defaults.update(overrides)
    return ListingResult(**defaults)


def test_passes_when_no_filters_set():
    assert passes_filters(_result(), _target()) is True


def test_fails_when_price_exceeds_max():
    assert passes_filters(_result(price=100.0), _target(max_price=50.0)) is False


def test_passes_when_price_within_max():
    assert passes_filters(_result(price=40.0), _target(max_price=50.0)) is True


def test_fails_when_include_keyword_missing():
    target = _target(keywords_include=["gaming"])
    assert passes_filters(_result(title="Blue Widget Pro"), target) is False


def test_passes_when_include_keyword_present_case_insensitive():
    target = _target(keywords_include=["WIDGET"])
    assert passes_filters(_result(title="Blue Widget Pro"), target) is True


def test_fails_when_exclude_keyword_present():
    target = _target(keywords_exclude=["ricondizionato"])
    assert passes_filters(_result(title="Widget Ricondizionato"), target) is False


def test_fails_when_seller_mismatch():
    target = _target(seller="OtherStore")
    assert passes_filters(_result(seller="Acme"), target) is False


def test_fails_when_condition_mismatch():
    target = _target(condition="used")
    assert passes_filters(_result(condition="new"), target) is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_filters.py -v`
Expected: FAIL with "No module named 'core.filters'"

- [ ] **Step 4: Implement `core/filters.py`**

```python
from __future__ import annotations

from core.config_loader import Target
from scrapers.base import ListingResult


def passes_filters(result: ListingResult, target: Target) -> bool:
    if target.max_price is not None and result.price > target.max_price:
        return False

    title_lower = result.title.lower()

    for keyword in target.keywords_include:
        if keyword.lower() not in title_lower:
            return False

    for keyword in target.keywords_exclude:
        if keyword.lower() in title_lower:
            return False

    if target.seller and (result.seller or "").lower() != target.seller.lower():
        return False

    if target.condition and (result.condition or "").lower() != target.condition.lower():
        return False

    return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_filters.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add scrapers/base.py core/filters.py tests/test_filters.py
git commit -m "feat: add scraper base interface and target filters"
```

---

### Task 3: Database layer (dedup + price-drop logic)

**Files:**
- Create: `core/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `scrapers.base.ListingResult`
- Produces: `core.database.Base`, `core.database.Listing` (SQLAlchemy model: `id, target_id, adapter, external_id, title, url, seller, condition, first_seen_at, last_seen_at, first_price, last_price, last_notified_price, notified_count`), `core.database.NotificationAction` (str Enum: `NONE`, `NEW`, `PRICE_DROP`), `core.database.compute_external_id(adapter: str, product_key: str) -> str`, `core.database.init_db(db_path: str) -> sessionmaker`, `core.database.process_listing(session, target_id: str, adapter: str, result: ListingResult, renotify_drop_pct: float) -> tuple[NotificationAction, Listing]`, `core.database.mark_notified(session, listing: Listing, price: float) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_database.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_database.py -v`
Expected: FAIL with "No module named 'core.database'"

- [ ] **Step 3: Implement `core/database.py`**

```python
from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from scrapers.base import ListingResult


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    adapter: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    seller: Mapped[str | None] = mapped_column(String, nullable=True)
    condition: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    first_price: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float] = mapped_column(Float)
    last_notified_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notified_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("target_id", "adapter", "external_id", name="uq_listing_identity"),
    )


class NotificationAction(str, enum.Enum):
    NONE = "none"
    NEW = "new"
    PRICE_DROP = "price_drop"


def compute_external_id(adapter: str, product_key: str) -> str:
    raw = f"{adapter}:{product_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def init_db(db_path: str) -> sessionmaker:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def process_listing(
    session: Session,
    target_id: str,
    adapter: str,
    result: ListingResult,
    renotify_drop_pct: float,
) -> tuple[NotificationAction, Listing]:
    external_id = compute_external_id(adapter, result.product_key)
    now = datetime.now(timezone.utc)

    listing = (
        session.query(Listing)
        .filter_by(target_id=target_id, adapter=adapter, external_id=external_id)
        .one_or_none()
    )

    if listing is None:
        listing = Listing(
            target_id=target_id,
            adapter=adapter,
            external_id=external_id,
            title=result.title,
            url=result.url,
            seller=result.seller,
            condition=result.condition,
            first_seen_at=now,
            last_seen_at=now,
            first_price=result.price,
            last_price=result.price,
            last_notified_price=None,
            notified_count=0,
        )
        session.add(listing)
    else:
        listing.last_seen_at = now
        listing.last_price = result.price
        listing.url = result.url

    if listing.last_notified_price is None:
        action = NotificationAction.NEW
    else:
        drop_pct = (listing.last_notified_price - result.price) / listing.last_notified_price
        action = NotificationAction.PRICE_DROP if drop_pct >= renotify_drop_pct else NotificationAction.NONE

    session.commit()
    return action, listing


def mark_notified(session: Session, listing: Listing, price: float) -> None:
    listing.last_notified_price = price
    listing.notified_count += 1
    session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_database.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add core/database.py tests/test_database.py
git commit -m "feat: add SQLite-backed dedup and price-drop detection"
```

---

### Task 4: Anti-bot helpers (jitter, retry/backoff, UA/proxy rotation)

**Files:**
- Create: `core/antibot.py`
- Test: `tests/test_antibot.py`

**Interfaces:**
- Produces: `core.antibot.RetryableError(Exception)`, `core.antibot.pick_user_agent(user_agents: list[str]) -> str`, `core.antibot.pick_proxy(proxies: list[str]) -> str | None`, `core.antibot.jittered_sleep(low: float, high: float) -> None` (async), `core.antibot.with_retry(fn: Callable[[], Awaitable[T]], max_retries: int, backoff_base_seconds: float) -> T` (async).

- [ ] **Step 1: Write the failing tests**

`tests/test_antibot.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_antibot.py -v`
Expected: FAIL with "No module named 'core.antibot'"

- [ ] **Step 3: Implement `core/antibot.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_antibot.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/antibot.py tests/test_antibot.py
git commit -m "feat: add anti-bot jitter, UA/proxy rotation, and retry helpers"
```

---

### Task 5: Mock scraper adapter

**Files:**
- Create: `scrapers/plugins/mock_adapter.py`
- Test: `tests/test_mock_adapter.py`

**Interfaces:**
- Consumes: `scrapers.base.BaseScraper`, `scrapers.base.ListingResult`, `core.config_loader.Target`
- Produces: `scrapers.plugins.mock_adapter.MockScraper` (adapter key `"mock"` for the engine registry in Task 8)

- [ ] **Step 1: Write the failing test**

`tests/test_mock_adapter.py`:
```python
from core.config_loader import Target
from scrapers.plugins.mock_adapter import MockScraper


async def test_mock_scraper_returns_result_under_max_price():
    target = Target(id="t1", adapter="mock", query="widget", max_price=50.0)
    scraper = MockScraper(antibot_config=None)

    results = await scraper.search(target)

    assert len(results) == 1
    assert results[0].price == 49.0
    assert "widget" in results[0].title.lower()


async def test_mock_scraper_defaults_price_without_max_price():
    target = Target(id="t2", adapter="mock", query="gadget")
    scraper = MockScraper(antibot_config=None)

    results = await scraper.search(target)

    assert results[0].price == 50.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mock_adapter.py -v`
Expected: FAIL with "No module named 'scrapers.plugins.mock_adapter'"

- [ ] **Step 3: Implement `scrapers/plugins/mock_adapter.py`**

```python
from __future__ import annotations

from core.config_loader import Target
from scrapers.base import BaseScraper, ListingResult


class MockScraper(BaseScraper):
    """Deterministic fake adapter used in tests; no network, no browser."""

    async def search(self, target: Target) -> list[ListingResult]:
        price = target.max_price - 1 if target.max_price else 50.0
        return [
            ListingResult(
                product_key=f"mock-{target.id}-1",
                title=f"{target.query} - Mock Result",
                url=f"https://example.com/mock/{target.id}",
                price=price,
                seller="MockStore",
                condition="new",
            )
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mock_adapter.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scrapers/plugins/mock_adapter.py tests/test_mock_adapter.py
git commit -m "feat: add deterministic mock scraper adapter for testing"
```

---

### Task 6: Telegram notifier

**Files:**
- Create: `core/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `core.database.Listing`, `core.database.NotificationAction`, `core.config_loader.Target`
- Produces: `core.notifier.format_message(listing: Listing, action: NotificationAction, target: Target) -> str`, `core.notifier.send_notification(bot: telegram.Bot, chat_id: str, message: str, max_retries: int = 2) -> bool` (async)

- [ ] **Step 1: Write the failing tests**

`tests/test_notifier.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notifier.py -v`
Expected: FAIL with "No module named 'core.notifier'"

- [ ] **Step 3: Implement `core/notifier.py`**

```python
from __future__ import annotations

import logging

from telegram import Bot
from telegram.error import TelegramError

from core.config_loader import Target
from core.database import Listing, NotificationAction

logger = logging.getLogger(__name__)


def format_message(listing: Listing, action: NotificationAction, target: Target) -> str:
    if action == NotificationAction.NEW:
        header = "🔥 *NUOVA OFFERTA RILEVATA!*"
        reference_price = target.max_price
        reference_label = "Prezzo target"
    else:
        header = "📉 *PREZZO SCESO ULTERIORMENTE!*"
        reference_price = listing.last_notified_price
        reference_label = "Prezzo precedente"

    price_line = f"💰 *Prezzo:* {listing.last_price:.2f} €"
    if reference_price is not None:
        price_line += f" ({reference_label}: {reference_price:.2f} €)"

    return (
        f"{header}\n"
        f"📦 *Prodotto:* {listing.title}\n"
        f"{price_line}\n"
        f"🏪 *Piattaforma:* {listing.adapter}\n"
        f"🔗 [Vai all'offerta]({listing.url})"
    )


async def send_notification(bot: Bot, chat_id: str, message: str, max_retries: int = 2) -> bool:
    attempt = 0
    while attempt <= max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            return True
        except TelegramError as e:
            attempt += 1
            logger.warning("Telegram send failed (attempt %d/%d): %s", attempt, max_retries, e)
    logger.error("Giving up sending Telegram notification after %d attempts", max_retries + 1)
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram message formatting and sending with retry"
```

---

### Task 7: Google Shopping scraper adapter

**Files:**
- Create: `scrapers/plugins/google_shopping.py`
- Test: `tests/test_google_shopping.py`

**Interfaces:**
- Consumes: `scrapers.base.BaseScraper`, `scrapers.base.ListingResult`, `core.antibot.RetryableError`, `core.antibot.pick_user_agent`, `core.antibot.pick_proxy`, `core.config_loader.AntibotConfig`, `core.config_loader.Target`
- Produces: `scrapers.plugins.google_shopping.parse_listings(html: str) -> list[ListingResult]` (pure, unit-testable), `scrapers.plugins.google_shopping.GoogleShoppingScraper` (adapter key `"google_shopping"` for the engine registry in Task 8)

**Note on selector fragility:** Google Shopping's DOM is undocumented and changes over time. This task ships a deterministic unit test against a hand-written HTML snippet that matches the selectors below, so the parsing logic itself is fully verified now. It also adds a second test, skipped until a real fixture is captured, so the selectors can be recalibrated against the live site without touching test infrastructure later.

- [ ] **Step 1: Write the failing tests**

`tests/test_google_shopping.py`:
```python
from pathlib import Path

import pytest

from scrapers.plugins.google_shopping import parse_listings

SYNTHETIC_HTML = """
<html><body>
<div class="sh-dgr__grid-result">
  <h3>Cuffie Bluetooth XYZ Pro</h3>
  <a href="/shopping/product/1"></a>
  <span aria-hidden="true">49,99&nbsp;€</span>
  <div class="aULzUe">NegozioA</div>
</div>
<div class="sh-dgr__grid-result">
  <h3>Cuffie Bluetooth ABC Lite</h3>
  <a href="https://negoziob.it/prodotto/2"></a>
  <span aria-hidden="true">1.234,50&nbsp;€</span>
  <div class="aULzUe">NegozioB</div>
</div>
</body></html>
"""

NO_PRICE_HTML = """
<div class="sh-dgr__grid-result">
  <h3>Prodotto senza prezzo</h3>
  <a href="/x"></a>
</div>
"""

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "google_shopping_sample.html"


def test_parse_listings_extracts_title_price_seller_url():
    listings = parse_listings(SYNTHETIC_HTML)

    assert len(listings) == 2

    first = listings[0]
    assert first.title == "Cuffie Bluetooth XYZ Pro"
    assert first.price == 49.99
    assert first.seller == "NegozioA"
    assert first.url == "https://www.google.com/shopping/product/1"

    second = listings[1]
    assert second.title == "Cuffie Bluetooth ABC Lite"
    assert second.price == 1234.50
    assert second.url == "https://negoziob.it/prodotto/2"


def test_parse_listings_skips_cards_without_price():
    assert parse_listings(NO_PRICE_HTML) == []


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="Real fixture not captured yet - see Task 7 Step 6 in the implementation plan",
)
def test_parse_listings_against_real_fixture():
    html = FIXTURE_PATH.read_text(encoding="utf-8")
    listings = parse_listings(html)
    assert len(listings) > 0
    for listing in listings:
        assert listing.title
        assert listing.price > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_google_shopping.py -v`
Expected: FAIL with "No module named 'scrapers.plugins.google_shopping'" (the fixture test will be SKIPPED, not failed, since the fixture file doesn't exist yet — that's expected).

- [ ] **Step 3: Implement `scrapers/plugins/google_shopping.py`**

```python
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from core.antibot import RetryableError, pick_proxy, pick_user_agent
from core.config_loader import AntibotConfig, Target
from scrapers.base import BaseScraper, ListingResult

logger = logging.getLogger(__name__)

SEARCH_URL_TEMPLATE = "https://www.google.com/search?tbm=shop&q={query}"
_PRICE_PATTERN = re.compile(r"[\d.,]+")


def _parse_price(raw_price: str) -> float | None:
    match = _PRICE_PATTERN.search(raw_price.replace("\xa0", " "))
    if not match:
        return None
    raw = match.group(0)
    normalized = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    try:
        return float(normalized)
    except ValueError:
        return None


def parse_listings(html: str) -> list[ListingResult]:
    """Parse a Google Shopping results page into ListingResult objects.

    Google Shopping's DOM structure is undocumented and changes over time.
    These selectors match the sample captured for this project (see
    tests/test_google_shopping.py); recapture a fresh fixture and adjust
    the selectors below if live results stop parsing.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: list[ListingResult] = []

    for card in soup.select("div.sh-dgr__grid-result, div.sh-dlr__list-result"):
        title_el = card.select_one("h3, h4")
        price_el = card.select_one("span[aria-hidden='true']")
        seller_el = card.select_one("div.aULzUe, div.IuHnof")
        link_el = card.select_one("a")

        if title_el is None or price_el is None:
            continue

        price = _parse_price(price_el.get_text())
        if price is None:
            continue

        title = title_el.get_text(strip=True)
        seller = seller_el.get_text(strip=True) if seller_el else None
        url = link_el["href"] if link_el and link_el.has_attr("href") else ""
        if url.startswith("/"):
            url = f"https://www.google.com{url}"

        product_key = f"{title}|{seller or ''}".lower()

        listings.append(
            ListingResult(
                product_key=product_key,
                title=title,
                url=url,
                price=price,
                seller=seller,
                condition=None,
            )
        )

    return listings


class GoogleShoppingScraper(BaseScraper):
    async def search(self, target: Target) -> list[ListingResult]:
        antibot_config: AntibotConfig = self.antibot_config
        url = SEARCH_URL_TEMPLATE.format(query=target.query.replace(" ", "+"))
        user_agent = pick_user_agent(antibot_config.user_agents)
        proxy_url = pick_proxy(antibot_config.proxies)

        launch_kwargs = {}
        if proxy_url:
            launch_kwargs["proxy"] = {"server": proxy_url}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, **launch_kwargs)
            try:
                context = await browser.new_context(user_agent=user_agent)
                page = await context.new_page()
                try:
                    response = await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError as e:
                    raise RetryableError(f"Timeout loading {url}") from e

                if response is not None and response.status in (403, 429):
                    raise RetryableError(
                        f"Blocked with HTTP {response.status} for query '{target.query}'"
                    )

                html = await page.content()
            finally:
                await browser.close()

        return parse_listings(html)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_google_shopping.py -v`
Expected: PASS (2 tests), 1 SKIPPED (real fixture test)

- [ ] **Step 5: Commit**

```bash
git add scrapers/plugins/google_shopping.py tests/test_google_shopping.py
git commit -m "feat: add Google Shopping scraper adapter with unit-tested parser"
```

- [ ] **Step 6: (Manual, post-plan) Capture a real fixture and recalibrate selectors**

This step is manual browser work, not automated code — do it once real Playwright/browser access is available:

1. Run `playwright install chromium` (needed once, downloads the browser binary).
2. Use Playwright codegen or a one-off script to open `https://www.google.com/search?tbm=shop&q=cuffie+bluetooth`, wait for results to render, and save `await page.content()` to `tests/fixtures/google_shopping_sample.html`.
3. Open the saved file and inspect the actual result-card markup (search for the product titles you expect to see).
4. Update the CSS selectors in `parse_listings` (`scrapers/plugins/google_shopping.py`) to match what you find, if they differ from the starting selectors.
5. Run `pytest tests/test_google_shopping.py -v` — the previously-skipped `test_parse_listings_against_real_fixture` should now run and pass.
6. Commit the fixture and any selector fixes: `git add tests/fixtures/google_shopping_sample.html scrapers/plugins/google_shopping.py && git commit -m "test: calibrate Google Shopping parser against real fixture"`.

---

### Task 8: Engine (ties adapters, dedup, and notifier together)

**Files:**
- Create: `core/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `core.antibot.{RetryableError, with_retry, jittered_sleep}`, `core.config_loader.{AppConfig, Target}`, `core.database.{NotificationAction, mark_notified, process_listing}`, `core.filters.passes_filters`, `core.notifier.{format_message, send_notification}`, `scrapers.base.BaseScraper`, `scrapers.plugins.google_shopping.GoogleShoppingScraper`, `scrapers.plugins.mock_adapter.MockScraper`
- Produces: `core.engine.SCRAPER_REGISTRY: dict[str, type[BaseScraper]]`, `core.engine.run_cycle(session_factory, config: AppConfig, targets: list[Target], bot, dry_run: bool = False) -> None` (async), `core.engine.run_forever(session_factory, config: AppConfig, targets: list[Target], bot, dry_run: bool = False) -> None` (async)

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL with "No module named 'core.engine'"

- [ ] **Step 3: Implement `core/engine.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_engine.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine.py
git commit -m "feat: add sequential polling engine wiring adapters, dedup, and notifier"
```

---

### Task 9: CLI entrypoint

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `core.config_loader.{load_config, ConfigError}`, `core.database.init_db`, `core.engine.{run_cycle, run_forever}`
- Produces: `main.build_arg_parser() -> argparse.ArgumentParser`, `main.main() -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
from main import build_arg_parser


def test_default_args():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.once is False
    assert args.dry_run is False
    assert args.config == "config/config.yaml"
    assert args.targets == "config/targets.json"


def test_once_and_dry_run_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["--once", "--dry-run"])
    assert args.once is True
    assert args.dry_run is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with "No module named 'main'"

- [ ] **Step 3: Implement `main.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Manual end-to-end smoke test with the mock adapter**

This verifies the full wiring (config → engine → database → notifier) without touching Telegram or Google:

1. Create a scratch targets file: `tests/fixtures/manual_mock_targets.json` with content `[{"id": "manual-check", "adapter": "mock", "query": "smoke test widget", "max_price": 50.0}]`.
2. Set dummy env vars and run once in dry-run mode:
   - PowerShell: `$env:TELEGRAM_BOT_TOKEN="000:dummy"; $env:TELEGRAM_CHAT_ID="1"; python main.py --once --dry-run --targets tests/fixtures/manual_mock_targets.json`
3. Expected log output includes a line starting with `[DRY RUN] Would send notification:` containing `🔥 *NUOVA OFFERTA RILEVATA!*` and the mock product title.
4. Run the same command again — expected: no `[DRY RUN]` line this time (same price, already notified, deduped).
5. Delete `data/crawler.db` (or the scratch DB) afterward if you don't want the smoke-test data kept.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS (one test remains SKIPPED: the real Google Shopping fixture test from Task 7, until Task 7 Step 6 is done manually).

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: add CLI entrypoint with --once and --dry-run support"
```

---

### Task 10: README and setup docs

**Files:**
- Create: `README.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Write `README.md`**

```markdown
# Crawler/Tracker con notifiche Telegram

Monitora offerte su Google Shopping (architettura a plugin, estendibile ad altri
marketplace) e invia notifiche Telegram in tempo reale per nuove offerte e cali di
prezzo significativi, senza mai duplicare notifiche per lo stesso prezzo.

## Setup

1. **Python 3.11+** richiesto.
2. Crea un virtualenv e installa le dipendenze:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements-dev.txt
   playwright install chromium
   ```
3. Copia `.env.example` in `.env` e compila i valori:
   ```bash
   copy .env.example .env
   ```
   - `TELEGRAM_BOT_TOKEN`: crea un bot con [@BotFather](https://t.me/BotFather) su Telegram, copia il token che ti fornisce.
   - `TELEGRAM_CHAT_ID`: scrivi un messaggio al tuo bot, poi apri
     `https://api.telegram.org/bot<TOKEN>/getUpdates` nel browser e leggi il campo
     `chat.id` nella risposta JSON (in alternativa usa il bot [@userinfobot](https://t.me/userinfobot)).
4. Modifica `config/targets.json` con le ricerche che vuoi monitorare (query, prezzo
   massimo, parole chiave da includere/escludere, venditore, condizione).
5. Rivedi `config/config.yaml` per intervalli di polling, proxy opzionali e soglia di
   ri-notifica sui cali di prezzo (`default_renotify_drop_pct`, default 5%).

## Esecuzione

- Singolo ciclo di prova, senza inviare notifiche reali:
  ```bash
  python main.py --once --dry-run
  ```
- Singolo ciclo, invio reale su Telegram:
  ```bash
  python main.py --once
  ```
- Loop continuo in background (comportamento di default):
  ```bash
  python main.py
  ```

## Test

```bash
pytest -v
```

Tutti i test girano senza rete o browser reale, usando un adapter mock
(`scrapers/plugins/mock_adapter.py`) e fixture HTML statiche per il parsing di Google
Shopping. Un test è marcato `skip` finché non viene catturata una fixture HTML reale
(vedi sotto).

## Calibrare l'adapter Google Shopping su una pagina reale

I selettori CSS in `scrapers/plugins/google_shopping.py` sono un punto di partenza:
Google cambia la struttura della pagina periodicamente. Per verificarli/aggiornarli:

1. `playwright install chromium` (se non già fatto).
2. Apri manualmente `https://www.google.com/search?tbm=shop&q=<query di prova>` con
   Playwright o un browser normale, salva l'HTML della pagina in
   `tests/fixtures/google_shopping_sample.html`.
3. Ispeziona l'HTML salvato e confronta con i selettori in `parse_listings()`.
4. Aggiorna i selettori se necessario, poi esegui `pytest tests/test_google_shopping.py -v`:
   il test `test_parse_listings_against_real_fixture` dovrebbe passare.

## Aggiungere un nuovo adapter/marketplace

1. Crea `scrapers/plugins/<nome>.py` con una classe che estende
   `scrapers.base.BaseScraper` e implementa `async def search(self, target) -> list[ListingResult]`.
2. Registra la classe in `SCRAPER_REGISTRY` in `core/engine.py`.
3. Usa `"adapter": "<nome>"` nei target di `config/targets.json`.
4. Aggiungi test di parsing con fixture HTML statiche, seguendo lo schema di
   `tests/test_google_shopping.py`.

## Struttura del progetto

```
crawler/
├── config/                  # config.yaml, targets.json
├── core/                     # engine, database, notifier, config loader, antibot, filters
├── scrapers/
│   ├── base.py                # interfaccia BaseScraper / ListingResult
│   └── plugins/                # adapter per marketplace/motori di ricerca
├── tests/
└── main.py                   # entrypoint CLI
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add setup, usage, and adapter-authoring instructions"
```

---

## Self-Review Notes

- **Spec coverage:** architettura a plugin (Task 2, 5, 7, 8), polling asincrono con jitter/UA rotation/retry su 429/403/timeout (Task 4, 7, 8), dedup SQLite (Task 3), notifiche Telegram (Task 6), config.yaml + targets.json (Task 1), README + test/mock (Task 5, 9, 10) — tutti i requisiti dello spec sono coperti da un task.
- **Placeholder scan:** nessun TBD; l'unico punto esplicitamente segnalato come "da ricalibrare" è la selettoristica CSS di Google Shopping (Task 7, Step 6), che è un'attività di verifica contro il sito live intrinseca allo scraping, non un'istruzione vaga — include passi concreti ed è accompagnata da un test deterministico che passa comunque senza fixture reale.
- **Type consistency:** `ListingResult.product_key` (Task 2) è usato in modo coerente in `database.py` (Task 3), `mock_adapter.py` (Task 5), `google_shopping.py` (Task 7). `NotificationAction` (Task 3) è usato in modo coerente in `notifier.py` (Task 6) ed `engine.py` (Task 8). Le firme di `process_listing`, `mark_notified`, `format_message`, `send_notification`, `run_cycle`, `run_forever` sono identiche ovunque vengano richiamate.
