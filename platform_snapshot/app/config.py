from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BB_", env_file=".env", extra="ignore")

    secret_key: str = "dev-only-secret-change-me"
    # Comma-separated previous secret keys, kept so stored credentials and
    # sessions survive a key rotation (see docs/DEPLOYMENT.md).
    old_secret_keys: str = ""
    database_url: str = "sqlite:///./brotherbot.db"
    base_url: str = "http://127.0.0.1:8000"
    env: str = "development"
    sweeper_enabled: bool = True
    sentry_dsn: str = ""

    # Payment providers (empty = provider hidden; wallet stays the ledger).
    stripe_secret_key: str = ""
    paypal_client_id: str = ""
    p24_merchant_id: str = ""

    # Invoice / VAT identity printed on invoices.
    vat_rate: float = 23.0
    company_name: str = "Brother Bot"
    company_address: str = ""
    company_vat_id: str = ""

    sms_provider: str = "console"
    twilio_sid: str = ""
    twilio_token: str = ""
    twilio_from: str = ""

    # Email — the default verification/recovery channel.
    # console (dev) | smtp | brevo (free tier: 300 mails/day)
    email_provider: str = "console"
    email_from: str = "Brother Bot <no-reply@localhost>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    brevo_api_key: str = ""

    brain_webhook_secret: str = "dev-brain-secret"

    session_ttl_hours: int = 24 * 14
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5

    # [SEC 08-01] wallet deposits auto-complete ONLY when this is explicitly on
    # (a local sandbox switch), never merely because env != production. Default
    # off closes the "any user self-credits their wallet in dev/staging" hole.
    wallet_autocredit_dev: bool = False

    # Defaults that must never survive into production.
    _INSECURE_DEFAULTS = {
        "secret_key": "dev-only-secret-change-me",
        "brain_webhook_secret": "dev-brain-secret",
    }

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def assert_secure_for_production(self) -> None:
        """[SEC 08-01] refuse to boot in production on shipped default secrets.
        Forging JWT sessions (admin takeover) and spoofing the brain webhook
        both hinge on these; a silent default is a full-compromise path."""
        if not self.is_production:
            return
        bad = [name for name, default in self._INSECURE_DEFAULTS.items()
               if getattr(self, name) == default]
        if bad:
            raise RuntimeError(
                "Refusing to start in production with default secret(s): "
                + ", ".join(f"BB_{n.upper()}" for n in bad)
                + " — set strong values (openssl rand -hex 32)."
            )

    @property
    def all_secret_keys(self) -> list[str]:
        """Current key first, then rotated-out keys (decrypt/verify fallback)."""
        old = [k.strip() for k in self.old_secret_keys.split(",") if k.strip()]
        return [self.secret_key, *old]


@lru_cache
def get_settings() -> Settings:
    return Settings()
