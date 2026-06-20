import os
import streamlit as st
import requests
import time
import json
import base64
import html
import re

from client.components.auth_guard import auth_guard
from client.components.chat_message import render_message, create_colored_avatar, strip_markdown_formatting
from client.utils.api_client import logout
from client.utils.query import (
    query_sync,
    query_langchain_sync,
    query_llamaindex_sync,
)

st.set_page_config(page_title="Chat - RAG Pipeline", page_icon="💬")

API_BASE_URL = "http://localhost:8000/api/v1"

# Parameter persistence
PARAM_FILE = "./data/chat_params.json"


def load_saved_params():
    import json

    if os.path.exists(PARAM_FILE):
        try:
            with open(PARAM_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_params(params):
    import json

    os.makedirs(os.path.dirname(PARAM_FILE), exist_ok=True)
    with open(PARAM_FILE, "w") as f:
        json.dump(params, f)


# Load saved parameters
saved_params = load_saved_params()

# Create avatar images once
AVATARS = {
    "cosine": create_colored_avatar("#3b82f6"),  # Blue
    "langchain": create_colored_avatar("#8b5cf6"),  # Purple
    "llamaindex": create_colored_avatar("#10b981"),  # Green
}

def _extract_user_id_from_token(token):
    """Extract the user ID (sub claim) from a JWT without verification.

    The JWT payload is base64url-encoded JSON. This is used client-side to
    derive a user-specific localStorage key for question history isolation.
    No cryptographic verification is needed — the backend validates the token
    on each API call.
    """
    try:
        payload_b64 = token.split(".")[1]
        # Add padding if needed for base64 decoding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("sub")
    except Exception:
        return None


# --- Question history cleanup on logout ---
# Check if a logout triggered a pending localStorage cleanup.
# This must run before auth_guard() so the cleanup JS is injected even when
# the page stops execution (no token).
cleanup_key = st.query_params.get("_qh_cleanup")
if cleanup_key and re.fullmatch(r"[a-f0-9]{8}", cleanup_key):
    st.markdown(
        f"""<script>localStorage.removeItem('rag_question_history_{cleanup_key}');</script>""",
        unsafe_allow_html=True,
    )
    del st.query_params["_qh_cleanup"]

auth_guard()

st.title("💬 Chat with Documents")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "question_history" not in st.session_state:
    st.session_state.question_history = []

# Derive user ID from JWT for localStorage key isolation
if "user_id" not in st.session_state:
    st.session_state.user_id = _extract_user_id_from_token(
        st.session_state.token
    )

headers = {"Authorization": f"Bearer {st.session_state.token}"}

# Model warmup status polling
if "models_ready" not in st.session_state:
    st.session_state.models_ready = False
if "models_poll_count" not in st.session_state:
    st.session_state.models_poll_count = 0

if not st.session_state.models_ready:
    models_placeholder = st.empty()

    try:
        health_resp = requests.get(f"{API_BASE_URL}/health/models", timeout=2, headers=headers)
        if health_resp.status_code == 200:
            model_data = health_resp.json()

            all_ready = True
            any_error = False

            with models_placeholder.container():
                st.markdown("### 🤖 Loading AI Models...")

                for model_key, display_name in [
                    ("cross_encoder", "Cross-Encoder Reranker"),
                    ("llm", "Language Model"),
                ]:
                    model_info = model_data.get(model_key, {})
                    status = model_info.get("status", "loading")
                    progress = model_info.get("progress", 0)
                    error = model_info.get("error")
                    model_name = model_info.get("model", "unknown")

                    if status == "ready":
                        all_ready = all_ready and True
                    elif status == "error":
                        any_error = True
                        st.error(f"⚠️ **{display_name}** failed to load: {error}")
                    else:
                        all_ready = False
                        st.markdown(f"**{display_name}** ({model_name})")
                        st.progress(int(progress))

                if any_error:
                    st.info(
                        "Some models failed to load. You can still use the chat, but some features may be unavailable."
                    )

            if all_ready:
                st.session_state.models_ready = True
                st.session_state.models_poll_count = 0
                models_placeholder.empty()
            else:
                st.session_state.models_poll_count = st.session_state.get("models_poll_count", 0) + 1
                if st.session_state.models_poll_count > 60:  # ~12 seconds max (60 × 0.2s)
                    st.session_state.models_ready = True
                    models_placeholder.empty()
                else:
                    # Note: time.sleep() blocks the Streamlit thread, but this is an
                    # acceptable pattern here because polling happens once per session
                    # before the user can interact with the chat. An async approach
                    # would require restructuring the page around st.rerun() callbacks.
                    time.sleep(0.2)
                    st.rerun()
    except requests.RequestException:
        # Health endpoint not available yet — server might be starting
        st.session_state.models_poll_count = st.session_state.get("models_poll_count", 0) + 1
        if st.session_state.models_poll_count > 30:  # ~30 seconds max (30 × 1s)
            st.session_state.models_ready = True
            models_placeholder.empty()
        else:
            time.sleep(1)
            st.rerun()

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

# Check if selected documents are still processing
processing_selected = []
for doc_id in selected_doc_ids:
    try:
        status_resp = requests.get(
            f"{API_BASE_URL}/documents/{doc_id}/status",
            headers=headers,
            timeout=5
        )
        if status_resp.status_code == 200:
            status_data = status_resp.json()
            if status_data.get("status") == "processing":
                processing_selected.append(status_data)
    except Exception:
        pass

if processing_selected:
    warning_lines = ["⚠️ **Documents still processing:**"]
    for ps in processing_selected:
        title = ps.get("title", "Unknown")
        pp = ps.get("parsing_progress", 0)
        cp = ps.get("chunking_progress", 0)
        sp = ps.get("saving_progress", 0)
        sc = ps.get("saved_chunks", 0)
        cc = ps.get("chunk_count", 0)

        parsing_icon = "✅" if pp == 100 else "🔄"
        chunking_icon = "✅" if cp == 100 else "🔄"

        if sp == 100:
            saving_icon = "✅"
        elif sp > 0:
            saving_icon = f"🔄 {sp}% ({sc}/{cc})"
        else:
            saving_icon = "⏳"

        warning_lines.append(
            f"- 📄 **{title}**  📄{parsing_icon}  ✂️{chunking_icon}  🧠{saving_icon}"
        )

    st.warning("\n".join(warning_lines))
    # Auto-refresh while docs are processing (only if no messages yet)
    if not st.session_state.messages:
        time.sleep(2)
        st.rerun()

# Sidebar - RAG implementation selection
st.sidebar.title("🔧 Compare RAG Implementations")

use_cosine = st.sidebar.checkbox("🔵 Cosine Sim", value=True, key="rag_cosine")
use_langchain = st.sidebar.checkbox("🟣 LangChain", value=True, key="rag_langchain")
use_llamaindex = st.sidebar.checkbox("🟢 LlamaIndex", value=True, key="rag_llamaindex")

# Build list of selected RAG implementations
selected_rags = []
if use_cosine:
    selected_rags.append("cosine")
if use_langchain:
    selected_rags.append("langchain")
if use_llamaindex:
    selected_rags.append("llamaindex")
st.session_state.selected_rags = selected_rags

# Sidebar - RAG Parameters
st.sidebar.title("⚙️ Parameters")

# Temperature slider (0.0 - 1.0)
temperature = st.sidebar.slider(
    "Temperature",
    min_value=0.0,
    max_value=1.0,
    value=saved_params.get("temperature", 0.5),
    step=0.1,
    key="rag_temperature",
    help="Lower = more factual, Higher = more creative",
)

# Max tokens slider (100 - 1000)
max_tokens = st.sidebar.slider(
    "Max Tokens",
    min_value=100,
    max_value=1000,
    value=saved_params.get("max_tokens", 600),
    step=100,
    key="rag_max_tokens",
    help="Maximum tokens in response",
)

# Top-K slider (1 - 10)
top_k = st.sidebar.slider(
    "Top-K",
    min_value=1,
    max_value=10,
    value=saved_params.get("top_k", 5),
    step=1,
    key="rag_top_k",
    help="Number of chunks to retrieve",
)

# Prompt Sources slider (1 - 10)
prompt_sources = st.sidebar.slider(
    "Sources in Prompt",
    min_value=1,
    max_value=10,
    value=saved_params.get("prompt_sources", 3),
    step=1,
    key="rag_prompt_sources",
    help="Number of chunks used in LLM prompt",
)

# Response Length dropdown
response_length = st.sidebar.selectbox(
    "Response Length",
    options=["concise", "normal", "detailed"],
    index=1,  # Default to "normal"
    key="rag_response_length",
    help="concise=brief, normal=standard, detailed=full",
)

# Show Citations checkbox
include_citations = st.sidebar.checkbox(
    "📝 Show Citations",
    value=saved_params.get("include_citations", True),
    key="rag_include_citations",
    help="When enabled, [Source N] citations are shown in responses",
)

if st.sidebar.button("💾 Save Parameters", use_container_width=True):
    save_params({
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_k": top_k,
        "prompt_sources": prompt_sources,
        "include_citations": include_citations,
    })
    st.sidebar.success("Parameters saved!")

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
    elif rag_type == "llamaindex":
        avatar_img = AVATARS["llamaindex"]
        label = "LlamaIndex"
    else:
        avatar_img = None
        label = ""
    msg_include_citations = message.get("include_citations", True)
    render_message(message["role"], message["content"], message.get("sources"), avatar_img=avatar_img, label=label, include_citations=msg_include_citations)

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
        
        # Check if any RAGs are selected
        if not selected_rags:
            st.error("Please select at least one RAG implementation")
            st.session_state.messages.pop()  # Remove the user message we just added
        else:
            # Get the parameter values from session state
            params = {
                "temperature": st.session_state.get("rag_temperature", 0.5),
                "max_tokens": st.session_state.get("rag_max_tokens", 600),
                "top_k": st.session_state.get("rag_top_k", 5),
                "prompt_sources": st.session_state.get("rag_prompt_sources", 3),
                "response_length": st.session_state.get("rag_response_length", "normal"),
                "include_citations": st.session_state.get("rag_include_citations", True),
            }
            
            # Get responses from selected RAG implementations
            if "cosine" in selected_rags:
                with st.chat_message("assistant", avatar=AVATARS["cosine"]):
                    with st.spinner("Cosine Similarity..."):
                        cosine_result = query_sync(
                            prompt, selected_doc_ids, **params
                        )
                        current_answer = cosine_result["answer"]
                        current_sources = cosine_result.get("sources", [])
                        current_include_citations = params["include_citations"]
                    st.markdown(f"**Cosine Similarity**\n\n{strip_markdown_formatting(current_answer, current_include_citations)}")
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": current_answer,
                    "sources": current_sources,
                    "rag_type": "cosine",
                    "include_citations": current_include_citations,
                })
            
            if "langchain" in selected_rags:
                with st.chat_message("assistant", avatar=AVATARS["langchain"]):
                    with st.spinner("LangChain..."):
                        langchain_result = query_langchain_sync(
                            prompt, selected_doc_ids, **params
                        )
                        langchain_answer = langchain_result["answer"]
                        langchain_sources = langchain_result.get("sources", [])
                        langchain_include_citations = params["include_citations"]
                    st.markdown(f"**LangChain**\n\n{strip_markdown_formatting(langchain_answer, langchain_include_citations)}")
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": langchain_answer,
                    "sources": langchain_sources,
                    "rag_type": "langchain",
                    "include_citations": langchain_include_citations,
                })
            
            if "llamaindex" in selected_rags:
                with st.chat_message("assistant", avatar=AVATARS["llamaindex"]):
                    with st.spinner("LlamaIndex..."):
                        llamaindex_result = query_llamaindex_sync(
                            prompt, selected_doc_ids, **params
                        )
                        llamaindex_answer = llamaindex_result["answer"]
                        llamaindex_sources = llamaindex_result.get("sources", [])
                        llamaindex_include_citations = params["include_citations"]
                    st.markdown(f"**LlamaIndex**\n\n{strip_markdown_formatting(llamaindex_answer, llamaindex_include_citations)}")
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": llamaindex_answer,
                    "sources": llamaindex_sources,
                    "rag_type": "llamaindex",
                    "include_citations": llamaindex_include_citations,
                })
            
            # --- Record question in history ---
            # Consecutive duplicate suppression: skip if same as most recent
            prompt_stripped = prompt.strip()
            if prompt_stripped and (
                not st.session_state.question_history
                or st.session_state.question_history[0] != prompt_stripped
            ):
                st.session_state.question_history.insert(0, prompt_stripped)
                # Cap at 200 entries, evict from the end
                if len(st.session_state.question_history) > 200:
                    st.session_state.question_history = st.session_state.question_history[:200]
        
        st.rerun()

# Clear chat button
if st.button("Clear Chat", type="secondary"):
    st.session_state.messages = []
    st.rerun()

# Compute user_id_hash (first 8 chars of UUID) for localStorage key isolation
_user_id = st.session_state.get("user_id", "")
_user_id_hash = _user_id[:8] if _user_id else ""

# Embed question history data in a hidden div for the JS to read on page load
st.markdown(
    f'<div id="q-history-data" data-history="{html.escape(json.dumps(st.session_state.question_history), quote=True)}" '
    f'data-user-hash="{_user_id_hash}"></div>',
    unsafe_allow_html=True,
)

# SECURITY NOTE (unsafe_allow_html): The hidden div above and the JS script below inject
# user-supplied question text into innerHTML via json.dumps() escaping. This is the second
# unsafe_allow_html=True usage in Chat.py (the first is the auto-focus script at lines ~440+).
# XSS mitigation: json.dumps() produces a properly escaped JSON string, so user text with
# special HTML characters is safely encoded. Questions are user-typed plain text (not rendered
# as markdown/HTML from untrusted sources), further reducing risk. The auto-focus script sets
# the same-risk precedent.

# Question history arrow-key navigation + auto-focus
st.markdown("""
<script>
(function() {
    var historyDiv = document.getElementById('q-history-data');
    if (!historyDiv) return;

    // --- Sync session history to localStorage ---
    var userHash = historyDiv.getAttribute('data-user-hash') || '';
    var storageKey = 'rag_question_history_' + userHash;
    var sessionHistory = [];
    try {
        sessionHistory = JSON.parse(historyDiv.getAttribute('data-history') || '[]');
    } catch(e) { /* ignore parse errors */ }

    // Merge unseen session entries into localStorage (prepend, no dupes)
    var stored = [];
    try {
        var raw = localStorage.getItem(storageKey);
        if (raw) stored = JSON.parse(raw);
    } catch(e) { /* ignore */ }

    var merged = sessionHistory.slice();  // session entries first (newest)
    var seen = new Set(merged);
    for (var i = 0; i < stored.length; i++) {
        if (!seen.has(stored[i])) {
            merged.push(stored[i]);
        }
    }
    if (merged.length > 200) merged = merged.slice(0, 200);
    localStorage.setItem(storageKey, JSON.stringify(merged));

    // --- Arrow-key navigation on chat input ---
    var history = merged;
    var historyIndex = -1;   // -1 = showing draft
    var savedDraft = '';

    function findChatInput() {
        var selectors = [
            'input[data-testid="stChatInputInput"]',
            '.stChatInput input',
            'input[type="text"]'
        ];
        for (var s = 0; s < selectors.length; s++) {
            var el = document.querySelector(selectors[s]);
            if (el) return el;
        }
        return null;
    }

    function retryFindChatInput(tries) {
        var el = findChatInput();
        if (el) return el;
        if (tries <= 0) return null;
        return new Promise(function(resolve) {
            setTimeout(function() {
                resolve(retryFindChatInput(tries - 1));
            }, 200);
        });
    }

    retryFindChatInput(10).then(function(chatInput) {
        if (!chatInput) return;
        if (chatInput.dataset.qhAttached) return;
        chatInput.dataset.qhAttached = 'true';

        chatInput.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (history.length === 0) return;

                if (historyIndex === -1) {
                    // First press: save current draft
                    savedDraft = chatInput.value;
                }

                if (historyIndex < history.length - 1) {
                    historyIndex++;
                    chatInput.value = history[historyIndex];
                }
                // If already at oldest entry, stay there
                chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
            }
            else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (historyIndex === -1) return;  // Already at draft

                historyIndex--;
                if (historyIndex === -1) {
                    // Return to saved draft
                    chatInput.value = savedDraft;
                } else {
                    chatInput.value = history[historyIndex];
                }
                chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
            }
        });
    });

    // Auto-focus the chat input
    setTimeout(function() {
        var chatInput = findChatInput();
        if (chatInput) chatInput.focus();
    }, 100);
})();
</script>
""", unsafe_allow_html=True)