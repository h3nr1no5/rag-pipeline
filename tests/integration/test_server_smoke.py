import pytest
import requests
import subprocess
import signal
import socket
import time
import os
import sys


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


@pytest.fixture(scope="module")
def server():
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}/api/v1"

    env = os.environ.copy()
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    env["HF_HUB_OFFLINE"] = "1"

    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    ready = False
    for _ in range(30):
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                ready = True
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)

    if not ready:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
        pytest.fail("Server did not become ready in time")

    yield base_url

    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


class TestServerSmoke:
    def test_health_endpoint(self, server):
        resp = requests.get(f"{server}/health", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "rag-pipeline"

    def test_docs_endpoint(self, server):
        resp = requests.get(f"{server.replace('/api/v1', '')}/docs", timeout=5)
        assert resp.status_code == 200

    def test_openapi_schema(self, server):
        resp = requests.get(
            f"{server.replace('/api/v1', '')}/openapi.json", timeout=5
        )
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "RAG Pipeline API"
