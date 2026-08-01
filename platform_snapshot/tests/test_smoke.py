"""Smoke tests over the whole route surface + core flows:
registration/OTP, auth gating, webhook mirror, API keys, emergency stop."""

PUBLIC_PAGES = [
    "/", "/features", "/pricing", "/performance", "/faq", "/docs-site",
    "/changelog", "/blog", "/status", "/contact", "/downloads",
    "/legal/terms", "/legal/privacy", "/legal/risk-disclaimer", "/legal/cookies", "/legal/gdpr",
    "/login", "/register", "/forgot", "/healthz",
]

DASH_PAGES = [
    "/dashboard", "/mt5", "/telegram", "/sms", "/bot", "/symbols", "/risk",
    "/copier", "/vps", "/signals", "/journal", "/analytics", "/subscription",
    "/wallet", "/affiliate", "/support", "/downloads/app", "/api-access",
    "/audit", "/security", "/profile",
]

ADMIN_PAGES = [
    "/admin", "/admin/users", "/admin/brokers", "/admin/finance", "/admin/ai",
    "/admin/engine", "/admin/servers", "/admin/notify", "/admin/cms",
    "/admin/reports", "/admin/compliance", "/admin/system",
]


def test_public_pages(client):
    for path in PUBLIC_PAGES:
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_dashboard_requires_login(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers["location"]


def test_registration_with_email_code(client, monkeypatch):
    import app.services.otp as otp_module

    monkeypatch.setattr(otp_module, "generate_otp", lambda: "424242")

    r = client.post("/register", data={
        "email": "NewUser@Example.org", "phone": "+48111222333", "password": "password123",
        "accept_terms": "1", "accept_risk": "1", "referral_code": "ref0001",
    }, follow_redirects=False)
    # Code goes to the email address (primary channel).
    assert r.status_code == 302 and "/verify?dest=newuser@example.org" in r.headers["location"]

    from app.database import SessionLocal
    from app.models.user import User

    r = client.post("/verify", data={"dest": "newuser@example.org", "code": "000001"})
    assert "Invalid" in r.text

    r = client.post("/verify", data={"dest": "newuser@example.org", "code": "424242"}, follow_redirects=False)
    assert r.status_code == 302 and "/dashboard" in r.headers["location"]

    db = SessionLocal()
    user = db.query(User).filter_by(email="newuser@example.org").first()
    assert user.email_verified and user.referred_by_id is not None
    db.close()
    client.get("/logout")

    # Login works with the email address too.
    r = client.post("/login", data={"phone": "newuser@example.org", "password": "password123"},
                    follow_redirects=False)
    assert r.status_code == 302 and "/dashboard" in r.headers["location"]
    client.get("/logout")


def test_registration_requires_email(client):
    r = client.post("/register", data={
        "password": "password123", "accept_terms": "1", "accept_risk": "1",
    })
    assert "email address is required" in r.text


def test_account_recovery_by_email(client, monkeypatch):
    import app.services.otp as otp_module
    from app.services import ratelimit

    ratelimit.reset_all()
    monkeypatch.setattr(otp_module, "generate_otp", lambda: "777777")

    r = client.post("/forgot", data={"dest": "newuser@example.org"})
    assert "recovery" in r.text.lower()
    r = client.post("/forgot/reset", data={"dest": "newuser@example.org", "code": "777777",
                                           "password": "brandnewpass1"}, follow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers["location"]
    r = client.post("/login", data={"phone": "newuser@example.org", "password": "brandnewpass1"},
                    follow_redirects=False)
    assert r.status_code == 302 and "/dashboard" in r.headers["location"]
    client.get("/logout")


def test_user_dashboard_pages(user_client):
    for path in DASH_PAGES:
        r = user_client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_user_cannot_access_admin(user_client):
    assert user_client.get("/admin").status_code == 403


def test_emergency_stop_and_audit(user_client):
    r = user_client.post("/risk/emergency-stop", follow_redirects=True)
    assert "EMERGENCY STOP IS ACTIVE" in r.text
    r = user_client.get("/audit")
    assert "EMERGENCY STOP engaged" in r.text
    user_client.post("/risk/resume")


def test_admin_pages(admin_client):
    for path in ADMIN_PAGES:
        r = admin_client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_brain_webhook_mirror(client):
    payload = {
        "system": "v18", "signal": "BUY", "direction": "BUY", "signal_id": "TEST-0001",
        "symbol": "GOLD", "tf": "M15", "entry": 4125.4, "sl": 4118.0, "tp": 4132.0,
        "tp1": 4132.0, "tp2": 4138.0, "rr": 1.4, "grade": "A",
        "council": {"approve": 6, "total": 6}, "status": "approved", "confidence": 92,
        "unknown_future_field": "passes-through",
    }
    # Wrong secret rejected.
    assert client.post("/webhooks/brain/signal", json=payload).status_code == 401
    r = client.post("/webhooks/brain/signal", json=payload, headers={"X-Brain-Secret": "test-brain-secret"})
    assert r.status_code == 200 and r.json()["ok"]

    # Append-only contract: raw payload stored verbatim, unknown keys kept.
    from app.database import SessionLocal
    from app.models.trading import Signal

    db = SessionLocal()
    sig = db.query(Signal).filter_by(signal_id="TEST-0001").first()
    assert sig.raw_payload["unknown_future_field"] == "passes-through"
    assert sig.status == "approved" and sig.tp2 == 4138.0
    db.close()


def test_api_key_flow(user_client):
    r = user_client.post("/api-access/keys/new", data={"label": "test", "permissions": "write"},
                         follow_redirects=False)
    key = r.headers["location"].split("new_key=")[1]
    assert key.startswith("bb_")

    api = {"Authorization": f"Bearer {key}"}
    assert user_client.get("/api/v1/me", headers=api).status_code == 200
    assert user_client.get("/api/v1/portfolio", headers=api).status_code == 200
    assert user_client.get("/api/v1/me").status_code == 401  # no key -> denied

    r = user_client.post("/api/v1/heartbeat/vps", headers=api,
                         json={"cpu_pct": 10, "ram_pct": 20, "ea_running": True, "mt5_running": True})
    assert r.status_code == 200

    r = user_client.post("/api/v1/heartbeat/account", headers=api,
                         json={"account_login": "52901228", "balance": 10100, "equity": 10150})
    assert r.status_code == 200


def test_subscription_needs_wallet_balance(user_client):
    # Enterprise costs more than any balance accumulated by earlier tests.
    r = user_client.post("/subscription/subscribe", data={"plan_slug": "enterprise"}, follow_redirects=True)
    assert "Insufficient wallet balance" in r.text
    user_client.post("/wallet/deposit", data={"amount": "600", "provider": "manual"})
    r = user_client.post("/subscription/subscribe", data={"plan_slug": "pro"}, follow_redirects=True)
    assert "Current plan: Pro" in r.text


def test_signal_pages_render(user_client):
    r = user_client.get("/signals?status=approved")
    assert r.status_code == 200
    r = user_client.get("/signals/1")
    assert r.status_code == 200


def test_maintenance_mode(admin_client, user_client):
    admin_client.post("/admin/system/maintenance")
    assert user_client.get("/dashboard").status_code == 503
    assert user_client.get("/admin", follow_redirects=False).status_code in (200, 302, 403)
    admin_client.post("/admin/system/maintenance")
    assert user_client.get("/dashboard").status_code == 200
