import streamlit as st


def auth_guard():
    if not st.session_state.get("token"):
        st.warning("Please login to access this page")
        st.stop()
