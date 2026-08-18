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


def test_validation_error_does_not_leak_bot_token(tmp_path, monkeypatch):
    # bot_token is present and valid, but chat_id is missing entirely, so
    # AppConfig validation fails. Pydantic's default ValidationError.__str__
    # would embed the whole input dict (including bot_token) in the message;
    # we assert the raised ConfigError does NOT contain the secret value.
    monkeypatch.setenv("TEST_BOT_TOKEN", "123456:SUPER-SECRET-TOKEN-VALUE")
    config_text = """
telegram:
  bot_token: "${TEST_BOT_TOKEN}"
polling:
  min_interval_seconds: 60
  max_interval_seconds: 120
"""
    config_path, targets_path = _write_files(tmp_path, config_text=config_text)

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_path, targets_path)

    assert "SUPER-SECRET-TOKEN-VALUE" not in str(exc_info.value)


def test_load_config_malformed_yaml_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    malformed_yaml = "telegram:\n  bot_token: x\n foo: [1, 2\n"
    config_path, targets_path = _write_files(tmp_path, config_text=malformed_yaml)

    with pytest.raises(ConfigError):
        load_config(config_path, targets_path)


def test_load_config_non_mapping_yaml_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    non_mapping_yaml = "- a\n- b\n"
    config_path, targets_path = _write_files(tmp_path, config_text=non_mapping_yaml)

    with pytest.raises(ConfigError):
        load_config(config_path, targets_path)
