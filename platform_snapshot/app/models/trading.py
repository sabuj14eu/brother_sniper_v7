from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import utcnow

DEFAULT_SYMBOLS = [
    "GOLD", "SILVER", "US100", "US30", "NAS100",
    "EURUSD", "GBPUSD", "USDJPY", "BTC", "ETH", "OIL",
]


class MT5Account(Base):
    __tablename__ = "mt5_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_name: Mapped[str] = mapped_column(String(120), default="")
    broker: Mapped[str] = mapped_column(String(120))
    server: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(32))
    # Investor (read-only) password recommended; encrypted at rest either way.
    password_enc: Mapped[str] = mapped_column(String(500), default="")
    password_kind: Mapped[str] = mapped_column(String(16), default="investor")  # investor|trading
    status: Mapped[str] = mapped_column(String(16), default="inactive")  # active|inactive|error
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)

    balance: Mapped[float] = mapped_column(Float, default=0.0)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    free_margin: Mapped[float] = mapped_column(Float, default=0.0)
    floating_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Sweeper flag: one bot-offline notification per outage, not one per minute.
    offline_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="mt5_accounts")
    trades = relationship("Trade", back_populates="account", cascade="all, delete-orphan")

    @property
    def is_online(self) -> bool:
        """Iron Rule 5: online means a *fresh heartbeat*, never a 200 response."""
        if not self.last_heartbeat_at:
            return False
        ts = self.last_heartbeat_at
        if ts.tzinfo is None:
            from datetime import timezone as _tz
            ts = ts.replace(tzinfo=_tz.utc)
        return (utcnow() - ts).total_seconds() < 300


class Signal(Base):
    """Read-only mirror of brain decisions. APPEND-ONLY payload contract:
    raw_payload keeps every field the brain sent, verbatim."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    system: Mapped[str] = mapped_column(String(16), default="v18")  # v18|v7
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    tf: Mapped[str] = mapped_column(String(16), default="")
    direction: Mapped[str] = mapped_column(String(8))  # BUY|SELL
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp2: Mapped[float | None] = mapped_column(Float, nullable=True)
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str] = mapped_column(String(8), default="")
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    council_votes: Mapped[dict] = mapped_column(JSON, default=dict)  # {"approve": 6, "total": 6, "members": {...}}
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending|approved|rejected|cancelled|executed
    reason: Mapped[str] = mapped_column(Text, default="")
    market_structure: Mapped[str] = mapped_column(Text, default="")
    screenshot_url: Mapped[str] = mapped_column(String(500), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="")  # win|loss|be|open|
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SignalEvent(Base):
    """AI Decision Replay: append-only timeline of everything that happened to
    a signal — original alert, council decision, executions, notifications."""

    __tablename__ = "signal_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    # alert_received|council_decision|status_change|mt5_execution|telegram_sent|outcome
    detail: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("mt5_accounts.id"), nullable=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    ticket: Mapped[str] = mapped_column(String(32), default="")
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # BUY|SELL
    lots: Mapped[float] = mapped_column(Float, default=0.01)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|pending|closed|cancelled
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)
    session: Mapped[str] = mapped_column(String(16), default="")  # asia|london|newyork|weekend
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Journal fields
    notes: Mapped[str] = mapped_column(Text, default="")
    emotion: Mapped[str] = mapped_column(String(32), default="")
    screenshot_url: Mapped[str] = mapped_column(String(500), default="")

    account = relationship("MT5Account", back_populates="trades")

    @property
    def duration_minutes(self) -> int | None:
        if self.close_time and self.open_time:
            return int((self.close_time - self.open_time).total_seconds() // 60)
        return None

    @property
    def net_profit(self) -> float:
        return round(self.profit + self.commission + self.swap, 2)


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    trading_mode: Mapped[str] = mapped_column(String(16), default="demo")  # demo|live|paper
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low|medium|high|custom
    lot_size: Mapped[float] = mapped_column(Float, default=0.01)
    max_trades: Mapped[int] = mapped_column(Integer, default=5)
    max_daily_loss: Mapped[float] = mapped_column(Float, default=3.0)  # percent
    max_daily_profit: Mapped[float] = mapped_column(Float, default=0.0)  # 0 = unlimited
    max_drawdown: Mapped[float] = mapped_column(Float, default=10.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=3)
    sessions: Mapped[dict] = mapped_column(JSON, default=lambda: {"asia": True, "london": True, "newyork": True, "weekend_crypto": False})
    news_filter: Mapped[bool] = mapped_column(Boolean, default=True)
    spread_filter: Mapped[bool] = mapped_column(Boolean, default=True)
    max_slippage: Mapped[float] = mapped_column(Float, default=2.0)
    auto_close_friday: Mapped[bool] = mapped_column(Boolean, default=True)
    trailing_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    break_even: Mapped[bool] = mapped_column(Boolean, default=True)
    partial_close: Mapped[bool] = mapped_column(Boolean, default=True)


class SymbolSetting(Base):
    __tablename__ = "symbol_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskLimits(Base):
    """Iron Rule 3: changes here are always audited; emergency stop is one click."""

    __tablename__ = "risk_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    daily_loss_limit: Mapped[float] = mapped_column(Float, default=3.0)
    weekly_loss_limit: Mapped[float] = mapped_column(Float, default=6.0)
    monthly_loss_limit: Mapped[float] = mapped_column(Float, default=10.0)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=4)
    max_exposure: Mapped[float] = mapped_column(Float, default=10.0)  # percent of equity
    max_lots: Mapped[float] = mapped_column(Float, default=1.0)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CopierLink(Base):
    __tablename__ = "copier_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    master_account_id: Mapped[int] = mapped_column(ForeignKey("mt5_accounts.id"))
    slave_account_id: Mapped[int] = mapped_column(ForeignKey("mt5_accounts.id"))
    copy_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    reverse_copy: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VPSStatus(Base):
    __tablename__ = "vps_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    cpu_pct: Mapped[float] = mapped_column(Float, default=0.0)
    ram_pct: Mapped[float] = mapped_column(Float, default=0.0)
    disk_pct: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    internet_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    ea_running: Mapped[bool] = mapped_column(Boolean, default=False)
    mt5_running: Mapped[bool] = mapped_column(Boolean, default=False)
    # Executor monitor extras
    mt5_version: Mapped[str] = mapped_column(String(32), default="")
    ea_version: Mapped[str] = mapped_column(String(32), default="")
    trade_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    queue_length: Mapped[int] = mapped_column(Integer, default=0)
    symbols_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_reconnect: Mapped[bool] = mapped_column(Boolean, default=True)
    last_order_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_order_fail_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_order_fail_reason: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketBias(Base):
    __tablename__ = "market_bias"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    trend: Mapped[str] = mapped_column(String(16), default="neutral")  # bullish|bearish|neutral
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    council_decision: Mapped[str] = mapped_column(String(120), default="")
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EconomicEvent(Base):
    __tablename__ = "economic_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    impact: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    affected_symbols: Mapped[list] = mapped_column(JSON, default=list)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
