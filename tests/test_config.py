"""Tests for env-aware configuration."""

import importlib


def test_wallet_paths_default():
    import src.config as config
    importlib.reload(config)
    assert config.WALLET_KEY_FILE == "/wallet_key.json"
    assert config.SERVER_WALLET_FILE == "/server_wallet.txt"


def test_wallet_paths_read_env(monkeypatch):
    monkeypatch.setenv("WALLET_KEY_FILE", "/tmp/custom_key.json")
    monkeypatch.setenv("SERVER_WALLET_FILE", "/tmp/custom_server.txt")
    import src.config as config
    importlib.reload(config)
    assert config.WALLET_KEY_FILE == "/tmp/custom_key.json"
    assert config.SERVER_WALLET_FILE == "/tmp/custom_server.txt"
    monkeypatch.delenv("WALLET_KEY_FILE")
    monkeypatch.delenv("SERVER_WALLET_FILE")
    importlib.reload(config)  # restore defaults for other tests
