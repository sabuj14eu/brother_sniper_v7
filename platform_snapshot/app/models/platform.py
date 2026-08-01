from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import utcnow

# Per-user Telegram notification toggles, all on by default.
TELEGRAM_EVENTS = [
    "buy", "sell", "pending", "close", "partial_close", "tp", "sl",
    "daily_report", "weekly_report", "monthly_report",
    "news_alert", "system_alert", "subscription_reminder",
]

NOTIFICATION_TYPES = [
    "trade_opened", "trade_closed", "sl_hit", "tp_hit", "margin_warning",
    "bot_offline", "server_restart", "subscription_expiry", "security", "system",
]


class TelegramSettings(Base):
    __tablename__ = "telegram_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    bot_token_enc: Mapped[str] = mapped_column(String(500), default="")
    chat_id: Mapped[str] = mapped_column(String(64), default="")
    events: Mapped[dict] = mapped_column(JSON, default=lambda: {e: True for e in TELEGRAM_EVENTS})
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class NotificationPrefs(Base):
    __tablename__ = "notification_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_trade_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_security_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_login_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_subscription_reminders: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # one of NOTIFICATION_TYPES
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32), default="support")
    # support|bug|feature|billing|remote_assistance
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|answered|closed
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # low|normal|high|urgent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket = relationship("Ticket", back_populates="messages")


class CMSPost(Base):
    __tablename__ = "cms_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    # blog|news|tutorial|faq|documentation|changelog|announcement|banner
    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    permissions: Mapped[list] = mapped_column(JSON, default=lambda: ["read"])  # read|write
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # brain|tradingview|user
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Broker(Base):
    __tablename__ = "brokers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    servers: Mapped[list] = mapped_column(JSON, default=list)
    supported_symbols: Mapped[list] = mapped_column(JSON, default=list)
    health: Mapped[str] = mapped_column(String(16), default="unknown")  # ok|degraded|down|unknown
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServerNode(Base):
    __tablename__ = "server_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    role: Mapped[str] = mapped_column(String(24))  # app|trading|redis|database|storage|queue|worker|cron
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # ok|degraded|down|unknown
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String(255), default="")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[str] = mapped_column(Text, default="")
