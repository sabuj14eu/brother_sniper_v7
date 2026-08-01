"""Payment provider registry. The wallet is the single money ledger; providers
only fund it. A provider appears in the UI once its credentials are set in the
environment — until then deposits are recorded as pending for manual/bank
confirmation.

Integration points (implement `create_checkout` per provider when going live):
- stripe: Checkout Session -> webhook /webhooks/payments/stripe marks tx completed
- paypal: Orders API -> capture webhook
- p24 (Przelewy24, PLN): transaction/register -> p24 status webhook
"""
from __future__ import annotations

from app.config import get_settings


def available_providers() -> list[dict]:
    s = get_settings()
    providers = [{"key": "manual", "label": "Bank transfer / manual", "ready": True}]
    providers.append({"key": "stripe", "label": "Card (Stripe)", "ready": bool(s.stripe_secret_key)})
    providers.append({"key": "paypal", "label": "PayPal", "ready": bool(s.paypal_client_id)})
    providers.append({"key": "p24", "label": "Przelewy24 (PLN)", "ready": bool(s.p24_merchant_id)})
    return providers


def create_checkout(provider: str, amount: float, user_id: int) -> str | None:
    """Returns a redirect URL for hosted checkout, or None for manual flow.
    Raises ValueError when the provider isn't configured."""
    if provider == "manual":
        return None
    ready = {p["key"]: p["ready"] for p in available_providers()}
    if not ready.get(provider):
        raise ValueError(f"Payment provider '{provider}' is not configured")
    # Real API calls go here (stripe.checkout.Session.create, etc.).
    raise ValueError(f"Provider '{provider}' configured but checkout not yet wired — use manual for now")
