import json
from pathlib import Path

import pytest

from app.config import (
    AppConfig,
    DEFAULT_URL,
    config_path,
    decrypt_password,
    encrypt_password,
    load_config,
    save_config,
)


def test_encrypt_roundtrip():
    plain = "shouna100"
    cipher = encrypt_password(plain)
    assert cipher != plain                  # 不裸存
    assert not cipher.startswith("shouna")  # 不含明文
    assert decrypt_password(cipher) == plain


def test_encrypt_not_plaintext_in_json(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.config_path", lambda: tmp_path / "config.json")
    cfg = AppConfig(username="u", password="secret123", export_dir="/tmp")
    path = save_config(cfg)
    raw = path.read_text(encoding="utf-8")
    assert "secret123" not in raw


def test_decrypt_plaintext_compat():
    # 旧版本明文值仍可读取
    assert decrypt_password("oldplain") == "oldplain"
    assert decrypt_password("") == ""


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.config_path", lambda: tmp_path / "config.json")
    cfg = AppConfig(url=DEFAULT_URL, username="宠趣汇旗舰店:以安",
                    password="p@ss", export_dir=str(tmp_path), page_timeout=45)
    save_config(cfg)
    loaded = load_config()
    assert loaded is not None
    assert loaded.url == cfg.url
    assert loaded.username == cfg.username
    assert loaded.password == "p@ss"
    assert loaded.page_timeout == 45


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.config_path", lambda: tmp_path / "nope.json")
    assert load_config() is None


def test_load_corrupt_returns_none(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("{ not valid json !!!", encoding="utf-8")
    monkeypatch.setattr("app.config.config_path", lambda: p)
    assert load_config() is None


def test_config_path_on_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    p = config_path()
    assert p.name == "config.json"
    assert ".qn-data-scraper" in str(p)
