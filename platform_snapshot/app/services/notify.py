"""Notification fan-out: in-app always; Telegram/SMS per user preference.
All outbound sends are best-effort and never block the request path hard."""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.models.platform import Notification, NotificationPrefs, TelegramSettings
from app.security import decrypt_secret

log = logging.getLogger("brotherbot.notify")


def send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200
    except httpx.HTTPError as exc:
        log.warning("telegram send failed: %s", exc)
        return False


def notify_user(
    db: Session,
    user_id: int,
    type: str,
    title: str,
    body: str = "",
    telegram_event: str | None = None,
    commit: bool = True,
) -> None:
    db.add(Notification(user_id=user_id, type=type, title=title, body=body))

    prefs = db.query(NotificationPrefs).filter_by(user_id=user_id).first()
    tg = db.query(TelegramSettings).filter_by(user_id=user_id).first()
    wants_telegram = (prefs is None or prefs.telegram_enabled) and tg and tg.verified and tg.bot_token_enc
    event_enabled = telegram_event is None or (tg and tg.events.get(telegram_event, True))
    if wants_telegram and event_enabled:
        try:
            send_telegram(decrypt_secret(tg.bot_token_enc), tg.chat_id, f"<b>{title}</b>\n{body}")
        except ValueError:
            log.warning("telegram token undecryptable for user %s", user_id)

    if commit:
        db.commit()


def format_signal_message(sig, account_label: str = "") -> str:
    """Matches the canonical Telegram message format from the spec."""
    emoji = "🟢" if sig.direction == "BUY" else "🔴"
    votes = sig.council_votes or {}
    lines = [
        f"{emoji} {sig.direction} {sig.symbol}",
        "",
        f"Entry: {sig.entry}",
        f"SL: {sig.sl}",
        f"TP1: {sig.tp1}",
    ]
    if sig.tp2:
        lines.append(f"TP2: {sig.tp2}")
    if votes:
        lines += ["", f"Council: {votes.get('approve', '?')}/{votes.get('total', '?')} Approved"]
    if sig.confidence:
        lines.append(f"Confidence: {round(sig.confidence)}%")
    if account_label:
        lines += ["", f"Account:\n{account_label}"]
    lines += ["", f"Time:\n{sig.created_at:%Y-%m-%d %H:%M} UTC"]
    return "\n".join(lines)
