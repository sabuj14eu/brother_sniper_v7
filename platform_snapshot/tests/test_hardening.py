"""Tests for the hardening pass: rate limits, secret rotation, duplicate
signals, decision replay, sweeper enforcement, metrics, invoices."""


def test_login_rate_limit_and_lockout(client):
    from app.services import ratelimit

    ratelimit.reset_all()
    for _ in range(10):
        client.post("/login", data={"phone": "+19999999999", "password": "wrong"})
    r = client.post("/login", data={"phone": "+19999999999", "password": "wrong"})
    assert "Too many attempts" in r.text
    ratelimit.reset_all()


def test_secret_rotation_decrypts_old_credentials(monkeypatch):
    from app.config import get_settings
    from app.security import decrypt_secret, encrypt_secret

    token = encrypt_secret("investor-pass-123")
    s = get_settings()
    old_key = s.secret_key
    monkeypatch.setattr(s, "secret_key", "brand-new-rotated-secret-key-000000")
    monkeypatch.setattr(s, "old_secret_keys", old_key)
    assert decrypt_secret(token) == "investor-pass-123"
    # New encryptions use the new key and still decrypt.
    assert decrypt_secret(encrypt_secret("fresh")) == "fresh"


def test_duplicate_signal_is_idempotent(client):
    payload = {"signal_id": "DUP-001", "symbol": "GOLD", "direction": "BUY",
               "entry": 4000, "status": "approved", "council": {"approve": 6, "total": 6}}
    h = {"X-Brain-Secret": "test-brain-secret"}
    assert client.post("/webhooks/brain/signal", json=payload, headers=h).status_code == 200
    assert client.post("/webhooks/brain/signal", json=payload, headers=h).status_code == 200

    from app.database import SessionLocal
    from app.models.trading import Signal

    db = SessionLocal()
    assert db.query(Signal).filter_by(signal_id="DUP-001").count() == 1
    db.close()


def test_decision_replay_timeline(client, user_client):
    h = {"X-Brain-Secret": "test-brain-secret"}
    client.post("/webhooks/brain/signal", headers=h, json={
        "signal_id": "REPLAY-001", "symbol": "SILVER", "direction": "SELL", "entry": 48.2,
        "status": "approved", "council": {"approve": 6, "total": 6}, "confidence": 88,
        "truth_layer": "confirmed", "macro": "risk-off"})
    # Executor reports the fill against the signal.
    r = user_client.post("/api-access/keys/new", data={"label": "replay", "permissions": "write"},
                         follow_redirects=False)
    key = r.headers["location"].split("new_key=")[1]
    r = user_client.post("/api/v1/heartbeat/trade", headers={"Authorization": f"Bearer {key}"},
                         json={"account_login": "52901228", "ticket": "REPLAY-T1", "symbol": "SILVER",
                               "direction": "SELL", "lots": 0.1, "entry_price": 48.2,
                               "signal_id": "REPLAY-001", "execution_latency_ms": 145})
    assert r.status_code == 200

    from app.database import SessionLocal
    from app.models.trading import Signal, SignalEvent

    db = SessionLocal()
    sig = db.query(Signal).filter_by(signal_id="REPLAY-001").first()
    stages = [e.stage for e in db.query(SignalEvent).filter_by(signal_id=sig.id).all()]
    db.close()
    assert "alert_received" in stages and "council_decision" in stages and "mt5_execution" in stages

    page = user_client.get(f"/signals/{sig.id}")
    assert "Decision replay timeline" in page.text and "truth layer" in page.text


def test_sweeper_auto_emergency_stop(client):
    from datetime import timedelta

    from app.database import SessionLocal
    from app.models.trading import MT5Account, RiskLimits, Trade
    from app.models.user import User, utcnow
    from app.services.sweeper import run_sweep

    db = SessionLocal()
    user = db.query(User).filter_by(phone="+10000000001").first()
    acc = db.query(MT5Account).filter_by(user_id=user.id).first()
    limits = db.query(RiskLimits).filter_by(user_id=user.id).first()
    limits.emergency_stop = False
    limits.daily_loss_limit = 1.0  # 1% of ~10k = 100
    now = utcnow()
    db.add(Trade(user_id=user.id, account_id=acc.id, ticket="SWEEP-1", symbol="GOLD", direction="BUY",
                 lots=0.5, entry_price=4000, exit_price=3990, status="closed", profit=-500,
                 open_time=now - timedelta(hours=2), close_time=now - timedelta(hours=1)))
    db.commit()

    result = run_sweep(db)
    assert result["auto_stops"] >= 1
    db.refresh(limits)
    assert limits.emergency_stop is True
    # cleanup so other tests aren't affected
    limits.emergency_stop = False
    db.query(Trade).filter_by(ticket="SWEEP-1").delete()
    db.commit()
    db.close()


def test_metrics_and_readyz(client):
    r = client.get("/metrics")
    assert r.status_code == 200 and "brotherbot_users_total" in r.text
    assert client.get("/readyz").json()["ok"] is True


def test_vat_invoice_page(user_client):
    from app.database import SessionLocal
    from app.models.billing import Invoice

    db = SessionLocal()
    inv = db.query(Invoice).order_by(Invoice.id.desc()).first()
    db.close()
    if inv is None:  # subscription test may not have run yet in this order
        user_client.post("/wallet/deposit", data={"amount": "200", "provider": "manual"})
        user_client.post("/subscription/subscribe", data={"plan_slug": "starter"})
        db = SessionLocal()
        inv = db.query(Invoice).order_by(Invoice.id.desc()).first()
        db.close()
    r = user_client.get(f"/invoices/{inv.id}")
    assert r.status_code == 200 and "INVOICE" in r.text and "VAT" in r.text


def test_csrf_cross_origin_rejected(user_client):
    r = user_client.post("/profile/save", data={"name": "x"},
                         headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
