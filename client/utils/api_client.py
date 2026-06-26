import base64
import json
import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")


def init_session_state():
    if "token" not in st.session_state:
        st.session_state.token = None
    if "user" not in st.session_state:
        st.session_state.user = None
    if "messages" not in st.session_state:
        st.session_state.messages = []


def get_headers():
    headers = {"Content-Type": "application/json"}
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    return headers


def login(email: str, password: str) -> dict | None:
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/login",
            json={"email": email, "password": password},
        )
        if response.status_code == 200:
            data = response.json()
            st.session_state.token = data["access_token"]
            return data
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def signup(email: str, password: str) -> dict | None:
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/signup",
            json={"email": email, "password": password},
        )
        if response.status_code == 201:
            return login(email, password)
        elif response.status_code == 400:
            error = response.json().get("detail", "Registration failed")
            st.error(error)
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def logout():
    # Compute user_id_hash before clearing for localStorage cleanup
    user_id_hash = ""
    token = st.session_state.get("token")
    if token:
        try:
            payload_b64 = token.split(".")[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            user_id = payload.get("sub", "")
            user_id_hash = user_id[:8]
        except Exception:
            pass
    if user_id_hash:
        st.query_params["_qh_cleanup"] = user_id_hash
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.messages = []
    st.session_state.selected_docs = []
