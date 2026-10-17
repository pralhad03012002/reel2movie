"""Tests for reel2movie.config: env-var loading via monkeypatch only.

No real credentials appear anywhere in this file; env vars are set/unset
per-test with pytest's monkeypatch fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reel2movie.config import (
    get_anthropic_key,
    get_instagram_cookies_file,
    get_tmdb_token,
    get_vision_backend,
)


def test_get_tmdb_token_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token-value")
    assert get_tmdb_token() == "fake-tmdb-token-value"


def test_get_tmdb_token_raises_when_unset(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
        get_tmdb_token()


def test_get_tmdb_token_raises_when_empty(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "")
    with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
        get_tmdb_token()


def test_get_anthropic_key_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key-value")
    assert get_anthropic_key() == "fake-anthropic-key-value"


def test_get_anthropic_key_raises_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_anthropic_key()


def test_get_anthropic_key_raises_when_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_anthropic_key()


def test_get_instagram_cookies_file_returns_path_when_set(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_COOKIES_FILE", "/tmp/ig_cookies.txt")
    result = get_instagram_cookies_file()
    assert result == Path("/tmp/ig_cookies.txt")


def test_get_instagram_cookies_file_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)
    assert get_instagram_cookies_file() is None


def test_get_instagram_cookies_file_returns_none_when_empty(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_COOKIES_FILE", "")
    assert get_instagram_cookies_file() is None


def test_get_vision_backend_defaults_to_claude_code_when_unset(monkeypatch):
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    assert get_vision_backend() == "claude_code"


def test_get_vision_backend_defaults_to_claude_code_when_empty(monkeypatch):
    monkeypatch.setenv("VISION_BACKEND", "")
    assert get_vision_backend() == "claude_code"


def test_get_vision_backend_returns_claude_code_when_explicitly_set(monkeypatch):
    monkeypatch.setenv("VISION_BACKEND", "claude_code")
    assert get_vision_backend() == "claude_code"


def test_get_vision_backend_returns_anthropic_api_when_explicitly_set(monkeypatch):
    monkeypatch.setenv("VISION_BACKEND", "anthropic_api")
    assert get_vision_backend() == "anthropic_api"


def test_get_vision_backend_raises_on_invalid_value(monkeypatch):
    monkeypatch.setenv("VISION_BACKEND", "something_else")
    with pytest.raises(RuntimeError, match="VISION_BACKEND"):
        get_vision_backend()
