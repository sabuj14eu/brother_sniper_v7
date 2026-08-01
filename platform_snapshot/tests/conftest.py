import os
import sys
from pathlib import Path

# Test database + deterministic secrets, set before the app imports settings.
os.environ["BB_DATABASE_URL"] = "sqlite:///./test_brotherbot.db"
os.environ["BB_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["BB_BRAIN_WEBHOOK_SECRET"] = "test-brain-secret"
os.environ["BB_SWEEPER_ENABLED"] = "false"
# tests exercise the wallet money-path; enable the dev-sandbox auto-credit flag
# (production never sets this — deposits stay pending there). See SEC 08-01 C2.
os.environ["BB_WALLET_AUTOCREDIT_DEV"] = "true"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    for f in ("test_brotherbot.db",):
        if os.path.exists(f):
            os.remove(f)
    from app.main import app
    import scripts.seed as seed

    seed.main()
    with TestClient(app) as c:
        yield c
    if os.path.exists("test_brotherbot.db"):
        os.remove("test_brotherbot.db")


@pytest.fixture(scope="session")
def user_client(client):
    """Separate client instance so login state never leaks into `client`."""
    from app.main import app
    from app.services import ratelimit

    ratelimit.reset_all()
    c = TestClient(app)
    c.post("/login", data={"phone": "+10000000001", "password": "demo1234"})
    return c


@pytest.fixture(scope="session")
def admin_client():
    from app.main import app

    c = TestClient(app)
    c.post("/login", data={"phone": "+10000000000", "password": "admin1234"})
    return c
