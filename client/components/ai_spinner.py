import streamlit as st
from contextlib import contextmanager


AI_SPINNER_HTML = """
<style>
.stSpinner > div {
    display: none !important;
}
.ai-spinner-container {
    display: flex !important;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: rgba(68, 70, 83, 0.1);
    border-radius: 8px;
    margin-top: 8px;
}
.ai-spinner-text {
    color: #666;
    font-size: 14px;
}
.ai-spinner-dots {
    display: flex;
    align-items: center;
    gap: 4px;
}
.ai-spinner-dot {
    width: 6px;
    height: 6px;
    background: #444652;
    border-radius: 50%;
    animation: ai-bounce 1.4s infinite ease-in-out both;
}
.ai-spinner-dot:nth-child(1) { animation-delay: -0.32s; }
.ai-spinner-dot:nth-child(2) { animation-delay: -0.16s; }
.ai-spinner-dot:nth-child(3) { animation-delay: 0s; }
@keyframes ai-bounce {
    0%, 80%, 100% { transform: scale(0); opacity: 0.4; }
    40% { transform: scale(1); opacity: 1; }
}
</style>
"""


@contextmanager
def ai_spinner(text: str = "Loading..."):
    st.markdown(AI_SPINNER_HTML, unsafe_allow_html=True)
    
    spinner_placeholder = st.empty()
    spinner_placeholder.markdown(
        f"""
        <div class="ai-spinner-container">
            <div class="ai-spinner-dots">
                <div class="ai-spinner-dot"></div>
                <div class="ai-spinner-dot"></div>
                <div class="ai-spinner-dot"></div>
            </div>
            <span class="ai-spinner-text">{text}</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    try:
        yield
    finally:
        spinner_placeholder.empty()
