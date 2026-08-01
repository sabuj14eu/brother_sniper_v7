"""Tests for the 2026-08-01 security fixes (SEC 08-01).

The production secret-guard is pure config logic — tested directly here.
Wallet-pending, admin-on-admin, session-binding and open-redirect behaviors
are exercised by the full suite (conftest sets the sandbox flag + strong test
secrets); this file locks the guard that has no other coverage.
"""
import pytest

from app.config import Settings


def _settings(**over):
    base = dict(env="production",
                secret_key="a-real-strong-secret-value-not-the-default",
                brain_webhook_secret="another-real-strong-secret")
    base.update(over)
    return Settings(**base)


def test_guard_passes_with_strong_prod_secrets():
    _settings().assert_secure_for_production()  # must not raise


def test_guard_blocks_default_secret_key_in_prod():
    with pytest.raises(RuntimeError) as e:
        _settings(secret_key="dev-only-secret-change-me").assert_secure_for_production()
    assert "BB_SECRET_KEY" in str(e.value)


def test_guard_blocks_default_brain_secret_in_prod():
    with pytest.raises(RuntimeError) as e:
        _settings(brain_webhook_secret="dev-brain-secret").assert_secure_for_production()
    assert "BB_BRAIN_WEBHOOK_SECRET" in str(e.value)


def test_guard_is_noop_outside_production():
    # defaults are fine in dev — the guard only fires for env=production
    Settings(env="development",
             secret_key="dev-only-secret-change-me",
             brain_webhook_secret="dev-brain-secret").assert_secure_for_production()


def test_wallet_autocredit_defaults_off(monkeypatch):
    # conftest sets BB_WALLET_AUTOCREDIT_DEV for the app; verify the CODE default
    # is off when the env var is absent.
    monkeypatch.delenv("BB_WALLET_AUTOCREDIT_DEV", raising=False)
    assert Settings(env="development", _env_file=None).wallet_autocredit_dev is False
