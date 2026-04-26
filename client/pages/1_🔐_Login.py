import streamlit as st
from client.utils.api_client import login, init_session_state
from client.components.ai_spinner import ai_spinner

st.set_page_config(page_title="Login - RAG Pipeline", page_icon="🔐")

init_session_state()

if st.session_state.token:
    st.switch_page("pages/3_💬_Chat.py")

st.title("🔐 Login")
st.markdown("Welcome back! Please login to continue.")

email = st.text_input("Email", placeholder="your@email.com")
password = st.text_input("Password", type="password")

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Login", use_container_width=True, type="primary"):
        if email and password:
            with ai_spinner("Logging in..."):
                result = login(email, password)
                if result:
                    st.success("Login successful!")
                    st.switch_page("pages/3_💬_Chat.py")
                else:
                    st.error("Invalid email or password")
        else:
            st.warning("Please fill in all fields")

with col2:
    if st.button("Create Account", use_container_width=True):
        st.switch_page("pages/2_📝_Signup.py")

st.divider()
st.markdown("Don't have an account? [Sign up here](/Signup)")
