"""Seed the database: plans, brokers, server nodes, demo admin + demo user
with realistic demo trading history, signals, bias, news and CMS content.

Run: python -m scripts.seed
Idempotent: safe to run twice (keys are checked before insert).
"""
from __future__ import annotations

import random
from datetime import timedelta

from app.database import SessionLocal, init_db
from app.models.billing import Plan
from app.models.platform import (
    Broker,
    CMSPost,
    FeatureFlag,
    NotificationPrefs,
    ServerNode,
    TelegramSettings,
)
from app.models.trading import (
    DEFAULT_SYMBOLS,
    BotSettings,
    EconomicEvent,
    MarketBias,
    MT5Account,
    RiskLimits,
    Signal,
    SymbolSetting,
    Trade,
    VPSStatus,
)
from app.models.user import User, utcnow
from app.security import encrypt_secret, hash_password

rng = random.Random(42)

PLANS = [
    dict(slug="free", name="Free", price_monthly=0, max_mt5_accounts=1, max_open_positions=1,
         features=["Signal feed (delayed)", "Community support"], sort_order=0),
    dict(slug="starter", name="Starter", price_monthly=29, max_mt5_accounts=1, max_open_positions=3,
         features=["Live signals", "Telegram alerts", "Email support"], sort_order=1),
    dict(slug="pro", name="Pro", price_monthly=79, max_mt5_accounts=3, max_open_positions=5,
         features=["Everything in Starter", "Trade copier", "Full analytics", "API access"], sort_order=2),
    dict(slug="vip", name="VIP", price_monthly=199, max_mt5_accounts=10, max_open_positions=10,
         features=["Everything in Pro", "Priority support", "Remote assistance"], sort_order=3),
    dict(slug="enterprise", name="Enterprise", price_monthly=499, max_mt5_accounts=50, max_open_positions=50,
         features=["Custom limits", "Dedicated infrastructure", "SLA"], sort_order=4),
]


def ensure_user(db, phone, password, role, name, email=None, **kw) -> User:
    user = db.query(User).filter_by(phone=phone).first()
    if user:
        return user
    user = User(phone=phone, phone_verified=True, email=email, email_verified=bool(email),
                password_hash=hash_password(password),
                role=role, name=name, referral_code=f"ref{phone[-4:]}", **kw)
    db.add(user)
    db.flush()
    db.add(BotSettings(user_id=user.id))
    db.add(RiskLimits(user_id=user.id))
    db.add(TelegramSettings(user_id=user.id))
    db.add(NotificationPrefs(user_id=user.id))
    db.add(VPSStatus(user_id=user.id, cpu_pct=23, ram_pct=41, disk_pct=37, latency_ms=18,
                     internet_ok=True, ea_running=True, mt5_running=True, updated_at=utcnow()))
    for sym in DEFAULT_SYMBOLS:
        db.add(SymbolSetting(user_id=user.id, symbol=sym,
                             enabled=sym in ("GOLD", "SILVER", "US100", "EURUSD")))
    return user


def main() -> None:
    init_db()
    db = SessionLocal()

    for p in PLANS:
        if not db.query(Plan).filter_by(slug=p["slug"]).first():
            db.add(Plan(**p))

    admin = ensure_user(db, "+10000000000", "admin1234", "superadmin", "Platform Admin",
                        email="admin@example.com")
    demo = ensure_user(db, "+10000000001", "demo1234", "user", "Demo Trader",
                       email="demo@example.com", country="Poland")

    if not db.query(MT5Account).filter_by(user_id=demo.id).first():
        db.add(MT5Account(
            user_id=demo.id, account_name="IC Markets Demo", broker="IC Markets",
            server="ICMarkets-Demo", login="52901228", password_enc=encrypt_secret("demo-investor-pass"),
            balance=10_000, equity=10_240, free_margin=9_800, floating_pnl=240,
            status="active", last_heartbeat_at=utcnow(),
        ))

    for name, servers in [("IC Markets", ["ICMarkets-Demo", "ICMarkets-Live01"]),
                          ("Pepperstone", ["Pepperstone-Demo", "Pepperstone-Edge"]),
                          ("FTMO", ["FTMO-Demo"])]:
        if not db.query(Broker).filter_by(name=name).first():
            db.add(Broker(name=name, servers=servers, supported_symbols=DEFAULT_SYMBOLS,
                          health="ok", latency_ms=rng.randint(8, 40)))

    for name, role in [("contabo-app-1", "app"), ("contabo-brain", "trading"),
                       ("redis-1", "redis"), ("pg-primary", "database"), ("worker-1", "worker")]:
        if not db.query(ServerNode).filter_by(name=name).first():
            db.add(ServerNode(name=name, role=role, status="ok", last_heartbeat_at=utcnow(),
                              metrics={"cpu": rng.randint(5, 40), "ram": rng.randint(20, 60)}))

    for key, desc in [("copier_enabled", "Trade copier module"),
                      ("mobile_api", "Mobile app API surface"),
                      ("weekend_crypto", "Weekend crypto sessions")]:
        if not db.query(FeatureFlag).filter_by(key=key).first():
            db.add(FeatureFlag(key=key, enabled=True, description=desc))

    # --- demo signals + trades over the last 60 days ------------------------
    if not db.query(Signal).first():
        symbols = ["GOLD", "SILVER", "US100", "EURUSD", "BTC"]
        sessions = ["asia", "london", "newyork"]
        now = utcnow()
        for i in range(80):
            created = now - timedelta(days=rng.uniform(0, 60))
            direction = rng.choice(["BUY", "SELL"])
            symbol = rng.choice(symbols)
            entry = round(rng.uniform(100, 4200), 2)
            approve = rng.choice([6, 6, 6, 5, 4, 3])
            status = "approved" if approve >= 5 else "rejected"
            win = rng.random() < (0.68 if symbol in ("SILVER", "US100") else 0.55)
            sig = Signal(
                signal_id=f"SIG-{created:%Y%m%d}-{i:04d}", system=rng.choice(["v18", "v18", "v7"]),
                symbol=symbol, tf=rng.choice(["M15", "H1", "H4"]), direction=direction,
                entry=entry, sl=round(entry * (0.995 if direction == "BUY" else 1.005), 2),
                tp1=round(entry * (1.004 if direction == "BUY" else 0.996), 2),
                tp2=round(entry * (1.008 if direction == "BUY" else 0.992), 2),
                rr=round(rng.uniform(0.8, 2.5), 2), grade=rng.choice(["A+", "A", "B", "C"]),
                ai_score=rng.randint(3, 10), confidence=rng.randint(55, 97),
                council_votes={"approve": approve, "total": 6},
                status=status,
                reason="Pullback trigger confirmed; structure aligned" if status == "approved"
                       else "Counter-trend entry vetoed by council",
                outcome=("win" if win else "loss") if status == "approved" else "",
                created_at=created,
            )
            db.add(sig)
            db.flush()
            if status == "approved":
                profit = round(rng.uniform(20, 180), 2) if win else -round(rng.uniform(15, 120), 2)
                opened = created + timedelta(minutes=2)
                db.add(Trade(
                    user_id=demo.id, account_id=db.query(MT5Account).filter_by(user_id=demo.id).first().id,
                    signal_id=sig.id, ticket=str(90_000_000 + i), symbol=symbol, direction=direction,
                    lots=0.1, entry_price=entry, exit_price=sig.tp1 if win else sig.sl,
                    sl=sig.sl, tp=sig.tp1, status="closed", profit=profit,
                    commission=-0.7, swap=0.0, rr=sig.rr, session=rng.choice(sessions),
                    open_time=opened, close_time=opened + timedelta(minutes=rng.randint(12, 480)),
                ))

    for sym, trend, conf in [("GOLD", "neutral", 52), ("SILVER", "bullish", 81), ("US100", "bullish", 77),
                             ("EURUSD", "bearish", 64), ("BTC", "bullish", 70), ("ETH", "neutral", 55),
                             ("DXY", "bearish", 60), ("OIL", "neutral", 48)]:
        if not db.query(MarketBias).filter_by(symbol=sym).first():
            db.add(MarketBias(symbol=sym, trend=trend, confidence=conf,
                              council_decision="trade with trend only", risk_level="medium"))

    if not db.query(EconomicEvent).first():
        now = utcnow()
        for title, hours, impact, cur, syms in [
            ("US CPI", 26, "high", "USD", ["GOLD", "US100", "EURUSD"]),
            ("FOMC Statement", 50, "high", "USD", ["GOLD", "US100", "DXY"]),
            ("ECB Rate Decision", 74, "medium", "EUR", ["EURUSD"]),
            ("US NFP", 120, "high", "USD", ["GOLD", "US100"]),
        ]:
            db.add(EconomicEvent(title=title, impact=impact, currency=cur,
                                 affected_symbols=syms, event_time=now + timedelta(hours=hours)))

    if not db.query(CMSPost).first():
        db.add_all([
            CMSPost(type="faq", title="Do I need to give you my trading password?", published=True,
                    slug="faq-passwords", author_id=admin.id,
                    body="No. We recommend the investor (read-only) password. A trading password is only "
                         "needed if your own executor requires it, and it is encrypted at rest."),
            CMSPost(type="faq", title="Can the bot trade without council approval?", published=True,
                    slug="faq-council", author_id=admin.id,
                    body="Never. Every signal passes the 6-agent council. The platform itself cannot "
                         "dispatch trades — it only observes and reports."),
            CMSPost(type="changelog", title="v1.0 — Platform launch", published=True,
                    slug="changelog-1-0", author_id=admin.id,
                    body="Multi-tenant platform: phone+OTP auth, MT5 management, Telegram alerts, "
                         "analytics, risk manager, subscriptions, affiliate, admin panels."),
            CMSPost(type="blog", title="Why every signal faces a 6-agent council", published=True,
                    slug="why-council", author_id=admin.id,
                    body="The last bypass lost 60R. Since then, nothing reaches an executor without "
                         "council approval. Here is how the council votes and what it vetoes..."),
            CMSPost(type="announcement", title="Demo accounts only during beta", published=True,
                    slug="beta-demo-only", author_id=admin.id,
                    body="During beta, all connected accounts must be demo accounts."),
        ])

    db.commit()
    db.close()
    print("Seed complete.")
    print("  superadmin: +10000000000 / admin1234")
    print("  demo user : +10000000001 / demo1234")


if __name__ == "__main__":
    main()
