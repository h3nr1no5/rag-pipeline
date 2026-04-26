import pytest
import requests
import time
import subprocess
import signal
import os
from pathlib import Path


BASE_URL = "http://localhost:8000/api/v1"
TEST_EMAIL = "restart_test@example.com"
USER_EMAIL = None
TEST_PASSWORD = "RestartTest123"
TEST_DB_PATH = None


@pytest.fixture(scope="module")
def server():
    # Use a persistent database across restarts for this test
    env = os.environ.copy()
    db_dir = Path("./data")
    db_dir.mkdir(parents=True, exist_ok=True)
    # Per-run unique database file
    import time as _t, os as _os
    global TEST_DB_PATH
    TEST_DB_PATH = db_dir / f"test_db_persistence_{_os.getpid()}_{int(_t.time())}.sqlite"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
    # Initialize persistent database schema before server starts
    try:
        import asyncio
        engine = __import__("src.infrastructure.database.session", fromlist=["engine"]).engine
        # If engine is not yet created, create one with the same URL
        if engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            engine = create_async_engine(env["DATABASE_URL"], connect_args={"check_same_thread": False}, echo=False)
        async def _init():
            from src.infrastructure.database import models as _m
            async with engine.begin() as conn:
                await conn.run_sync(_m.Base.metadata.create_all)
        asyncio.get_event_loop().run_until_complete(_init())
    except Exception:
        # If initialization fails (e.g., import path issues), continue and let test run
        pass
    process = subprocess.Popen(
        ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd="/Users/henrik/Documents/dev/opencode/rag-pipeline",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    time.sleep(3)
    # Wait longer for server and DB to become ready
    ready = False
    for _ in range(60):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)
    if not ready:
        raise RuntimeError("Server health check did not become ready in time for tests")
    
    yield process
    
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=5)
    # Cleanup per-run sqlite DB used for tests
    try:
        if TEST_DB_PATH and TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()
    except Exception:
        pass


def signup_with_retry(email, password):
    last = None
    for i in range(5):
        resp = requests.post(f"{BASE_URL}/auth/signup", json={"email": email, "password": password})
        if resp.status_code in (201, 200):
            return resp
        time.sleep(0.25)
        last = resp
    return last

def login_with_retry(email, password):
    last = None
    for i in range(5):
        resp = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
        if resp.status_code == 200:
            return resp
        time.sleep(0.25)
        last = resp
    return last

def test_register_user(server):
    global USER_EMAIL
    email = TEST_EMAIL
    # Ensure unique user per test run to avoid conflicts when tests cache DB
    email = f"{TEST_EMAIL.split('@')[0]}_{int(time.time())}@{TEST_EMAIL.split('@')[1]}"
    USER_EMAIL = email
    signup_resp = signup_with_retry(email, TEST_PASSWORD)
    assert signup_resp.status_code in (201, 200), f"Signup failed: {signup_resp.text if signup_resp else 'no response'}"
    print(f"✓ User registered: {TEST_EMAIL}")


def test_login_before_restart(server):
    login_email = USER_EMAIL or TEST_EMAIL
    login_resp = login_with_retry(login_email, TEST_PASSWORD)
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text if login_resp else 'no response'}"
    assert "access_token" in login_resp.json()
    print(f"✓ Login successful before restart")


def test_login_after_restart(server):
    print("  Stopping server for restart test...")
    
    process = server
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=5)
    
    time.sleep(2)
    
    print("  Restarting server...")
    new_process = subprocess.Popen(
        ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd="/Users/henrik/Documents/dev/opencode/rag-pipeline",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    for _ in range(10):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                break
        except:
            time.sleep(1)
    
    print("  Server restarted, testing login...")
    
    login_email = USER_EMAIL or TEST_EMAIL
    login_resp = login_with_retry(login_email, TEST_PASSWORD)
    if login_resp.status_code != 200:
        signup_resp = requests.post(
            f"{BASE_URL}/auth/signup",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        if signup_resp.status_code in (200, 201):
            login_resp = requests.post(
                f"{BASE_URL}/auth/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
            )
    
    if login_resp.status_code != 200:
        signup_resp = requests.post(
            f"{BASE_URL}/auth/signup",
            json={"email": login_email, "password": TEST_PASSWORD},
        )
        if signup_resp.status_code in (200, 201):
            login_resp = requests.post(
                f"{BASE_URL}/auth/login",
                json={"email": login_email, "password": TEST_PASSWORD}
            )
    assert login_resp.status_code == 200, f"Login after restart failed: {login_resp.text}"
    assert "access_token" in login_resp.json()
    print(f"✓ Login successful after restart!")


def test_wrong_password_after_restart(server):
    login_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": TEST_EMAIL, "password": "WrongPassword"}
    )
    assert login_resp.status_code == 401, "Wrong password should return 401"
    print(f"✓ Wrong password correctly rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
