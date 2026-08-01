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

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def all_secret_keys(self) -> list[str]:
        """Current key first, then rotated-out keys (decrypt/verify fallback)."""
        old = [k.strip() for k in self.old_secret_keys.split(",") if k.strip()]
        return [self.secret_key, *old]


@lru_cache
def get_settings() -> Settings:
    return Settings()
