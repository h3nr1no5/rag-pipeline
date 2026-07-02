import pytest
import uuid
import time
from pathlib import Path

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_login_flow(backend_server, frontend_server, page):
    """Test the login flow with a newly created user."""
    backend_url = backend_server["base_url"]
    frontend_url = frontend_server
    
    # Create a test user via backend API
    import httpx
    test_email = f"e2e_test_{uuid.uuid4().hex[:8]}@test.com"
    test_password = "test123"
    
    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        # Sign up the user
        resp = client.post("/api/v1/auth/signup", 
                          json={"email": test_email, "password": test_password})
        assert resp.status_code == 201, f"Failed to create user: {resp.text}"
    
    # Navigate to frontend
    page.goto(frontend_url)
    
    # Click "🔐 Login" button on home page
    login_button = page.get_by_role("button", name="Login")
    login_button.click()
    # Wait for the login page to load
    page.wait_for_url("**/Login**", timeout=15000)
    
    # Debug screenshot after navigation to login page
    page.screenshot(path=str(Path("./data/test_screenshots") / "after_login_nav.png"))
    
    # Fill in login form using robust locators
    # Use data-testid-based locator which is more reliable in Streamlit
    email_input = page.locator('[data-testid="stTextInput"]').first.locator('input')
    email_input.fill(test_email)
    
    # Password field uses input[type="password"]
    password_input = page.locator('input[type="password"]')
    password_input.fill(test_password)
    
    # Click login submit button using explicit locator
    login_submit = page.locator('[data-testid="stButton"] button').first
    login_submit.click()
    
    # Wait for redirect to chat page
    page.wait_for_url("**/Chat**", timeout=30000)
    
    # Verify we're on the chat page
    assert "💬 Chat with Documents" in page.content()
    
    # Take screenshot on success
    screenshot_dir = Path("./data/test_screenshots")
    screenshot_dir.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshot_dir / "login_flow_success.png"))


def test_full_flow_no_document(backend_server, frontend_server, page):
    """Test the chat page renders correctly without any documents uploaded."""
    backend_url = backend_server["base_url"]
    frontend_url = frontend_server
    screenshot_dir = Path("./data/test_screenshots")
    screenshot_dir.mkdir(exist_ok=True)

    import httpx
    test_email = f"e2e_test_{uuid.uuid4().hex[:8]}@test.com"
    test_password = "test123"

    # ── 1. Create user via backend API ─────────────────────────────────────
    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        resp = client.post("/api/v1/auth/signup",
                           json={"email": test_email, "password": test_password})
        assert resp.status_code == 201, f"Failed to create user: {resp.text}"

    # ── 2. Login via frontend (same as test_login_flow) ────────────────────
    page.goto(frontend_url)

    login_button = page.get_by_role("button", name="Login")
    login_button.click()
    page.wait_for_url("**/Login**", timeout=15000)

    email_input = page.locator('[data-testid="stTextInput"]').first.locator('input')
    email_input.fill(test_email)

    password_input = page.locator('input[type="password"]')
    password_input.fill(test_password)

    login_submit = page.locator('[data-testid="stButton"] button').first
    login_submit.click()

    # ── 3. Wait for Chat page URL ─────────────────────────────────────────
    page.wait_for_url("**/Chat**", timeout=30000)

    # ── 4. Verify the "Select a document" guidance message ─────────────────
    select_doc_msg = page.locator("text=Select a document")
    select_doc_msg.wait_for(state="visible", timeout=30000)
    assert select_doc_msg.is_visible(), "Expected 'Select a document' guidance message not found"

    # ── 5. Take screenshot ─────────────────────────────────────────────────
    page.screenshot(path=str(screenshot_dir / "no_document_flow_success.png"))


def test_login_flow_failure(backend_server, frontend_server, page):
    """Test login flow with invalid credentials."""
    backend_url = backend_server["base_url"]
    frontend_url = frontend_server
    
    # Navigate to frontend
    page.goto(frontend_url)
    
    # Click "🔐 Login" button on home page
    login_button = page.get_by_role("button", name="Login")
    login_button.click()
    # Wait for the login page to load
    page.wait_for_url("**/Login**", timeout=15000)
    
    # Debug screenshot after navigation to login page
    page.screenshot(path=str(Path("./data/test_screenshots") / "after_login_nav.png"))
    
    # Fill in invalid login form using robust locators
    email_input = page.locator('[data-testid="stTextInput"]').first.locator('input')
    email_input.fill("invalid@example.com")
    
    password_input = page.locator('input[type="password"]')
    password_input.fill("wrongpassword")
    
    # Click login submit button using explicit locator
    login_submit = page.locator('[data-testid="stButton"] button').first
    login_submit.click()
    
    # Wait for error message to appear
    error_message = page.locator('text=Invalid email or password')
    page.wait_for_selector('text=Invalid email or password', timeout=10000)
    
    # Verify error message is shown
    assert error_message.is_visible()
    
    # Take screenshot on failure
    screenshot_dir = Path("./data/test_screenshots")
    screenshot_dir.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshot_dir / "login_flow_failure.png"))


def test_full_flow(backend_server, frontend_server, page):
    """Test the complete RAG pipeline: upload document and chat with it."""
    backend_url = backend_server["base_url"]
    frontend_url = frontend_server
    screenshot_dir = Path("./data/test_screenshots")
    screenshot_dir.mkdir(exist_ok=True)

    import httpx
    test_email = f"e2e_test_{uuid.uuid4().hex[:8]}@test.com"
    test_password = "test123"

    # ── 1. Create user via backend API ─────────────────────────────────────
    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        resp = client.post("/api/v1/auth/signup",
                           json={"email": test_email, "password": test_password})
        assert resp.status_code == 201, f"Failed to create user: {resp.text}"

    # ── 2. Login via backend API to get JWT token ─────────────────────────
    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        resp = client.post("/api/v1/auth/login",
                           json={"email": test_email, "password": test_password})
        assert resp.status_code == 200, f"Failed to login: {resp.text}"
        token = resp.json()["access_token"]

    # ── 3. Upload a test document via backend API ──────────────────────────
    test_doc_path = Path("./tests/docs/test docx.docx")
    assert test_doc_path.exists(), f"Test document not found: {test_doc_path}"

    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        with open(test_doc_path, "rb") as f:
            upload_resp = client.post(
                "/api/v1/documents",
                files={
                    "file": (
                        test_doc_path.name,
                        f,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                },
                data={"strategy_id": "api-docs"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert upload_resp.status_code == 201, f"Failed to upload document: {upload_resp.text}"
        document_id = upload_resp.json()["id"]

    # ── 4. Poll document status until "completed" ─────────────────────────
    with httpx.Client(base_url=backend_url, timeout=60.0) as client:
        deadline = time.monotonic() + 300
        doc_status = "pending"
        while time.monotonic() < deadline:
            status_resp = client.get(
                f"/api/v1/documents/{document_id}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert status_resp.status_code == 200, f"Status check failed: {status_resp.text}"
            doc_status = status_resp.json()["status"]
            if doc_status == "completed":
                elapsed = 300 - (deadline - time.monotonic())
                print(f"Document processing completed in {elapsed:.0f}s")
                break
            time.sleep(2)
        else:
            raise TimeoutError(
                f"Document did not complete processing within 300s "
                f"(last status: {doc_status})"
            )

    # ── 5. Login to frontend (same flow as test_login_flow) ───────────────
    page.goto(frontend_url)

    login_button = page.get_by_role("button", name="Login")
    login_button.click()
    page.wait_for_url("**/Login**", timeout=15000)

    email_input = page.locator('[data-testid="stTextInput"]').first.locator('input')
    email_input.fill(test_email)

    password_input = page.locator('input[type="password"]')
    password_input.fill(test_password)

    login_submit = page.locator('[data-testid="stButton"] button').first
    login_submit.click()

    # ── 6. Wait for Chat page URL ────────────────────────────────────────
    page.wait_for_url("**/Chat**", timeout=30000)

    # ── 7. Wait for chat input textarea ───────────────────────────────────
    page.locator('[data-testid="stChatInputTextArea"]').wait_for(state="visible", timeout=120000)

    # ── 8. Type a question and press Enter ────────────────────────────────
    chat_input = page.locator('[data-testid="stChatInputTextArea"]')
    chat_input.fill("how to change logo?")
    chat_input.press("Enter")

    # ── 9. Wait for assistant response ────────────────────────────────────
    page.wait_for_function(
        '''() => {
            const messages = document.querySelectorAll('[data-testid="stChatMessageContent"]');
            return Array.from(messages).some(msg => {
                const parent = msg.closest('[data-testid="stChatMessage"]');
                return parent && !parent.textContent.includes('You:');
            });
        }''',
        timeout=300000  # 5 minutes for model inference
    )

    # ── 10. Verify response has content ───────────────────────────────────
    assistant_messages = page.locator('[data-testid="stChatMessageContent"]:not(:has-text("You:"))')
    assert assistant_messages.count() > 0, "No assistant messages found"

    first_assistant_msg = assistant_messages.first
    msg_text = first_assistant_msg.text_content()
    assert msg_text and msg_text.strip(), "Assistant message is empty"

    print(f"Assistant response: {msg_text[:200]}...")

    # ── 11. Take screenshot ───────────────────────────────────────────────
    page.screenshot(path=str(screenshot_dir / "full_flow_success.png"))
