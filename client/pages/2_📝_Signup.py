import streamlit as st

from client.components.ai_spinner import ai_spinner
from client.utils.api_client import init_session_state, signup

st.set_page_config(page_title="Signup - RAG Pipeline", page_icon="📝")

init_session_state()

if st.session_state.token:
    st.switch_page("pages/3_💬_Chat.py")

st.title("📝 Create Account")
st.markdown("Join RAG Pipeline to start chatting with your documents.")

email = st.text_input("Email", placeholder="your@email.com", key="signup_email")
password = st.text_input("Password", type="password", help="Minimum 6 characters", key="signup_password")  # noqa: E501
confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Sign Up", use_container_width=True, type="primary"):
        if not email or not password or not confirm_password:
            st.warning("Please fill in all fields")
        elif password != confirm_password:
            st.error("Passwords do not match")
        elif len(password) < 6:
            st.error("Password must be at least 6 characters")
        else:
            with ai_spinner("Creating account..."):
                result = signup(email, password)
                if result:
                    st.success("Account created! Redirecting...")
                    st.switch_page("pages/3_💬_Chat.py")

with col2:
    if st.button("Back to Login", use_container_width=True):
        st.switch_page("pages/1_🔐_Login.py")

st.divider()
st.markdown("Already have an account? [Login here](/Login)")
