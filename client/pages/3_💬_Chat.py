import streamlit as st
import requests

from client.components.auth_guard import auth_guard
from client.components.chat_message import render_message, create_colored_avatar
from client.utils.api_client import logout
from client.utils.query import (
    stream_query_with_placeholder,
    stream_query_langchain_with_placeholder,
)

st.set_page_config(page_title="Chat - RAG Pipeline", page_icon="💬")

API_BASE_URL = "http://localhost:8000/api/v1"

# Create avatar images once
AVATARS = {
    "cosine": create_colored_avatar("#3b82f6"),  # Blue
    "langchain": create_colored_avatar("#8b5cf6"),  # Purple
}

auth_guard()

st.title("💬 Chat with Documents")

if "messages" not in st.session_state:
    st.session_state.messages = []

headers = {"Authorization": f"Bearer {st.session_state.token}"}

# Get documents
try:
    response = requests.get(f"{API_BASE_URL}/documents", headers=headers)
    if response.status_code == 200:
        documents = response.json().get("documents", [])
    else:
        documents = []
except Exception:
    documents = []

display_titles = [f"{doc['title']}" for doc in documents]
display_map = {doc["title"]: doc["id"] for doc in documents}

# Sidebar - document selection
st.sidebar.title("📁 Select Documents")
current_selected = st.session_state.get("selected_docs", [])
valid_selections = [t for t in current_selected if t in display_titles]

# Auto-select first document if none selected and documents exist
if not valid_selections and display_titles:
    valid_selections = [display_titles[0]]

selected_titles = st.sidebar.multiselect(
    "Choose documents:",
    options=display_titles,
    default=valid_selections,
    key="docs_multiselect",
)
st.session_state.selected_docs = selected_titles
selected_doc_ids = [display_map[t] for t in selected_titles if t in display_map]

if not selected_doc_ids:
    st.info("👈 Select a document to start chatting")

if st.sidebar.button("Logout", use_container_width=True):
    logout()
    st.rerun()

# Show all messages FIRST
for message in st.session_state.messages:
    rag_type = message.get("rag_type", "")
    if message["role"] == "user":
        avatar_img = None
        label = ""
    elif rag_type == "cosine":
        avatar_img = AVATARS["cosine"]
        label = "Cosine Similarity"
    elif rag_type == "langchain":
        avatar_img = AVATARS["langchain"]
        label = "LangChain"
    else:
        avatar_img = None
        label = ""
    if label:
        content = f"**{label}**\n\n{message['content']}"
    else:
        content = message["content"]
    render_message(message["role"], content, message.get("sources"), avatar_img=avatar_img)

# Chat input at bottom
if prompt := st.chat_input("Ask a question...", key="chat_input"):
    if not selected_doc_ids:
        st.error("Please select a document")
    else:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "sources": []
        })
        
        # Render user message immediately so it stays visible during loading phase
        render_message("user", prompt)
        
        # Get responses from both RAG implementations
        with st.chat_message("assistant", avatar=AVATARS["cosine"]):
            with st.spinner("Cosine Similarity..."):
                current_answer, current_sources, _ = stream_query_with_placeholder(prompt, selected_doc_ids)
            st.markdown(f"**Cosine Similarity**\n\n{current_answer}")
        
        with st.chat_message("assistant", avatar=AVATARS["langchain"]):
            with st.spinner("LangChain..."):
                langchain_answer, langchain_sources, _ = stream_query_langchain_with_placeholder(prompt, selected_doc_ids)
            st.markdown(f"**LangChain**\n\n{langchain_answer}")
        
        # Add assistant messages
        st.session_state.messages.append({
            "role": "assistant",
            "content": current_answer,
            "sources": current_sources,
            "rag_type": "cosine"
        })
        st.session_state.messages.append({
            "role": "assistant",
            "content": langchain_answer,
            "sources": langchain_sources,
            "rag_type": "langchain"
        })
        
        st.rerun()

# Clear chat button
if st.button("Clear Chat", type="secondary"):
    st.session_state.messages = []
    st.rerun()

# Auto-focus chat input on page load
st.markdown("""
<script>
    // Wait for Streamlit to fully load, then focus the chat input
    setTimeout(function() {
        const chatInput = document.querySelector('input[data-testid="stChatInputInput"]') 
                      || document.querySelector('.stChatInput input')
                      || document.querySelector('input[type="text"]');
        if (chatInput) {
            chatInput.focus();
        }
    }, 100);
</script>
""", unsafe_allow_html=True)