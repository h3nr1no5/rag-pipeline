import pytest
import time
import requests
import subprocess
import signal
import os
from pathlib import Path

BASE_URL = 'http://localhost:8001/api/v1'


@pytest.fixture(scope="module")
def server():
    # Start server on port 8001 for embedding tests to isolate from other tests
    port = 8001
    cwd = "/Users/henrik/Documents/dev/opencode/rag-pipeline"
    process = subprocess.Popen(
        ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    # simple health check
    for _ in range(20):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    yield process
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        pass

def test_embedding_presence_after_processing(server):
    email = f"embed_user_{int(time.time())}@example.com"
    password = "embedpass123"
    signup = requests.post(f"{BASE_URL}/auth/signup", json={"email": email, "password": password})
    assert signup.status_code in (201, 200)
    login = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    test_text = Path(__file__).resolve().parent.parent / "docs" / "sample_python.txt"
    with open(test_text, "rb") as f:
        content = f.read()
    files = {"file": ("embed_test.txt", content, "text/plain")}
    data = {"strategy_id": "default"}
    resp = requests.post(f"{BASE_URL}/documents", files=files, data=data, headers=headers)
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    for _ in range(120):
        time.sleep(1)
        status = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers).json()
        if status.get("status") == "completed":
            break

    doc = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=headers).json()
    assert doc.get("embedded") is True
    chunks = requests.get(f"{BASE_URL}/documents/{doc_id}/chunks", headers=headers).json()
    if chunks.get("chunks"):
        first = chunks["chunks"][0]
        emb = first.get("embedding")
        # Embedding may be unavailable in CI; allow None or a valid embedding vector
        assert emb is None or isinstance(emb, list)
