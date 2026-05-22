import streamlit as st

st.set_page_config(
    page_title="RAG Pipeline",
    page_icon="🤖",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.stSpinner > div {
    display: none !important;
}
[data-testid="stChatMessageContent"] h1,
[data-testid="stChatMessageContent"] h2,
[data-testid="stChatMessageContent"] h3,
[data-testid="stChatMessageContent"] h4,
[data-testid="stChatMessageContent"] h5,
[data-testid="stChatMessageContent"] h6 {
    font-size: 1.1rem !important;
    font-weight: 600 !important;
    margin: 0.5rem 0 0.25rem 0 !important;
    padding: 0 !important;
    border-bottom: none !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🤖 RAG Pipeline")
st.markdown("Chat with your documents using local AI")

st.markdown("""
### Getting Started

1. **Create an account** or login
2. **Upload documents** (PDF, DOCX, TXT, or OpenAPI specs)
3. **Chat** with your documents using natural language

### Features

- 🔒 **User Authentication** - Secure access to your documents
- 📄 **Multi-format Support** - PDF, Word, Text, and OpenAPI specs
- 💬 **Streaming Responses** - Real-time AI answers
- 📦 **Query Caching** - 3-day cache for faster responses
- 🎯 **API-Aware** - Understands API endpoints and schemas
- 🏠 **Local LLM** - Runs on your machine with MLX
""")

col1, col2 = st.columns(2)

with col1:
    if st.button("🔐 Login", use_container_width=True, type="primary"):
        st.switch_page("pages/1_🔐_Login.py")

with col2:
    if st.button("📝 Sign Up", use_container_width=True):
        st.switch_page("pages/2_📝_Signup.py")

st.divider()
st.caption("Built with FastAPI, Streamlit, and MLX")
