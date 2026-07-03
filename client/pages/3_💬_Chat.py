import base64
import html
import json
import logging
import os
import re
import time

import requests
import streamlit as st
from streamlit import fragment

from client.components.auth_guard import auth_guard
from client.components.chat_message import (
    create_colored_avatar,
    render_message,
    strip_markdown_formatting,
)
from client.utils.api_client import logout
from client.utils.query import (
    async_query_poll,
    async_query_start,
)

st.set_page_config(page_title="Chat - RAG Pipeline", page_icon="💬")

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")

# Parameter persistence
PARAM_FILE = "./data/chat_params.json"


def load_saved_params():
    import json

    if os.path.exists(PARAM_FILE):
        try:
            with open(PARAM_FILE) as f:
                loaded = json.load(f)
            # Clamp max_tokens to 1200 for safe migration
            if "max_tokens" in loaded and loaded["max_tokens"] > 1200:
                logger = logging.getLogger(__name__)
                logger.warning(
                    "Clamping saved max_tokens %d to 1200",
                    loaded["max_tokens"],
                )
                loaded["max_tokens"] = 1200
            return loaded
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
    "api_docs": create_colored_avatar("#f59e0b"),  # Amber for API docs
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
    st.html(
        f"""<script>localStorage.removeItem('rag_question_history_{cleanup_key}');</script>""",
        unsafe_allow_javascript=True,
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
if "models_permanent_error" not in st.session_state:
    st.session_state.models_permanent_error = False
if "dspy_ready" not in st.session_state:
    st.session_state.dspy_ready = False

# Async query task state
if "active_task_id" not in st.session_state:
    st.session_state.active_task_id = None
if "active_query_params" not in st.session_state:
    st.session_state.active_query_params = None
if "task_started" not in st.session_state:
    st.session_state.task_started = False

if not st.session_state.models_ready:
    models_placeholder = st.empty()

    try:
        health_resp = requests.get(f"{API_BASE_URL}/health/models", timeout=2, headers=headers)
        if health_resp.status_code == 200:
            model_data = health_resp.json()

            # Max-polls guard
            st.session_state.models_poll_count += 1
            if st.session_state.models_poll_count >= 50:
                st.session_state.models_permanent_error = True
                with models_placeholder.container():
                    st.error("⚠️ Models failed to load within the expected time. Please refresh the page or restart the server.")  # noqa: E501

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

                dspy_info = model_data.get("dspy_lm", {})
                st.session_state.dspy_ready = dspy_info.get("status") == "ready"

                if any_error:
                    st.info(
                        "Some models failed to load. You can still use the chat, but some features may be unavailable."  # noqa: E501
                    )

            if all_ready:
                st.session_state.models_ready = True
                st.session_state.models_poll_count = 0
                models_placeholder.empty()
            else:
                time.sleep(1.0)
                st.rerun()
    except requests.RequestException:
        st.session_state.models_poll_count += 1
        if st.session_state.models_poll_count >= 50:
            st.session_state.models_permanent_error = True
            with models_placeholder.container():
                st.error("⚠️ Unable to connect to the server after multiple attempts. Please ensure the backend is running and refresh the page.")  # noqa: E501
        else:
            time.sleep(1.0)
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

_is_querying = st.session_state.get("task_started", False)
selected_titles = st.sidebar.multiselect(
    "Choose documents:",
    options=display_titles,
    default=valid_selections,
    key="docs_multiselect",
    disabled=_is_querying,
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

# Check if any selected documents have api-docs engine type
api_doc_ids = []
if selected_doc_ids:
    for doc in documents:
        if doc["id"] in selected_doc_ids:
            strategy = doc.get("chunking_strategy", {})
            if strategy.get("engine_type") == "api-docs":
                api_doc_ids.append(doc["id"])

show_api_docs = len(api_doc_ids) > 0
# Filter selected_doc_ids to only those that exist in the documents list
valid_selected_ids = [doc_id for doc_id in selected_doc_ids
                      if any(d["id"] == doc_id for d in documents)]
all_api_docs = show_api_docs and len(api_doc_ids) == len(valid_selected_ids)

_api_docs_help = "Not available for API documentation documents"
use_cosine = st.sidebar.checkbox(
    "🔵 Cosine Sim", value=True, key="rag_cosine",
    disabled=all_api_docs or _is_querying, help=_api_docs_help if all_api_docs else None,
)
use_langchain = st.sidebar.checkbox(
    "🟣 LangChain", value=True, key="rag_langchain",
    disabled=all_api_docs or _is_querying, help=_api_docs_help if all_api_docs else None,
)
use_llamaindex = st.sidebar.checkbox(
    "🟢 LlamaIndex", value=True, key="rag_llamaindex",
    disabled=all_api_docs or _is_querying, help=_api_docs_help if all_api_docs else None,
)

# Poll API doc index status
api_docs_ready = False
if api_doc_ids:
    try:
        status_resp = requests.get(
            f"{API_BASE_URL}/query/api-docs/documents/{api_doc_ids[0]}/status",
            headers=headers,
            timeout=5,
        )
        if status_resp.status_code == 200:
            api_docs_ready = status_resp.json().get("indexed", False)
    except Exception:
        pass

if show_api_docs:
    use_api_docs = st.sidebar.checkbox(
        "🔶 API Docs",
        value=True,
        key="rag_api_docs",
        disabled=not api_docs_ready or not st.session_state.dspy_ready or _is_querying,
        help=("DSPy LM is still initializing..." if not st.session_state.dspy_ready else
              "API doc model is warming up..." if not api_docs_ready else
              "Query API documentation"),
    )
    verification_enabled = st.sidebar.checkbox(
        "Enable answer verification",
        value=True,
        key="rag_api_docs_verification",
        disabled=_is_querying,
        help="Disabling lets the model answer freely but may increase hallucinations",
    )
else:
    use_api_docs = False
    verification_enabled = True

# Build list of selected RAG implementations
selected_rags = []
if use_cosine and not all_api_docs:
    selected_rags.append("cosine")
if use_langchain and not all_api_docs:
    selected_rags.append("langchain")
if use_llamaindex and not all_api_docs:
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
    disabled=_is_querying,
    help="Lower = more factual, Higher = more creative",
)

# Max tokens slider (64 - 1200)
max_tokens = st.sidebar.slider(
    "Max Tokens",
    min_value=64,
    max_value=1200,
    value=saved_params.get("max_tokens", 600),
    step=64,
    key="rag_max_tokens",
    disabled=_is_querying,
    help="Maximum tokens in response (higher = more room for reasoning, max 1200)",
)

# Top-K slider (1 - 10)
top_k = st.sidebar.slider(
    "Top-K",
    min_value=1,
    max_value=10,
    value=saved_params.get("top_k", 5),
    step=1,
    key="rag_top_k",
    disabled=_is_querying,
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
    disabled=_is_querying,
    help="Number of chunks used in LLM prompt",
)

# Response Length dropdown
response_length = st.sidebar.selectbox(
    "Response Length",
    options=["concise", "normal", "detailed"],
    index=1,  # Default to "normal"
    key="rag_response_length",
    disabled=_is_querying,
    help="concise=brief, normal=standard, detailed=full",
)

# Show Citations checkbox
include_citations = st.sidebar.checkbox(
    "📝 Show Citations",
    value=saved_params.get("include_citations", True),
    key="rag_include_citations",
    disabled=_is_querying,
    help="When enabled, [Source N] citations are shown in responses",
)

# Clean Response checkbox
clean_response = st.sidebar.checkbox(
    "🧹 Clean Response",
    value=saved_params.get("clean_response", False),
    key="rag_clean_response",
    disabled=_is_querying,
    help="When enabled, response cleaning pipeline is applied (dedup, strip tokens, etc.)",
)

if st.sidebar.button("💾 Save Parameters", use_container_width=True, disabled=_is_querying):
    save_params({
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_k": top_k,
        "prompt_sources": prompt_sources,
        "include_citations": include_citations,
        "clean_response": clean_response,
    })
    st.sidebar.success("Parameters saved!")

if not selected_doc_ids:
    st.info("👈 Select a document to start chatting")

if st.sidebar.button("Logout", use_container_width=True):
    logout()
    st.rerun()

# Show all messages FIRST
if st.session_state.messages:
    logger = logging.getLogger(__name__)
    logger.debug("Rendering %d stored messages", len(st.session_state.messages))
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
    elif rag_type == "api_docs":
        avatar_img = AVATARS["api_docs"]
        label = "API Documentation"
    else:
        avatar_img = None
        label = ""
    msg_include_citations = message.get("include_citations", True)
    render_message(message["role"], message["content"], message.get("sources"), avatar_img=avatar_img, label=label, include_citations=msg_include_citations)  # noqa: E501

    # Show confidence badge and expandable sections for API docs
    if rag_type == "api_docs":
        confidence = message.get("confidence", None)
        if confidence is not None:
            if confidence >= 0.7:
                st.markdown(f"<span style='color:green;font-weight:bold;'>🟢 Confidence: {confidence:.2f}</span>", unsafe_allow_html=True)  # noqa: E501
            elif confidence >= 0.4:
                st.markdown(f"<span style='color:#eab308;font-weight:bold;'>🟡 Confidence: {confidence:.2f}</span>", unsafe_allow_html=True)  # noqa: E501
            else:
                st.markdown(f"<span style='color:red;font-weight:bold;'>🔴 Confidence: {confidence:.2f}</span>", unsafe_allow_html=True)  # noqa: E501

        reasoning_hint = message.get("reasoning_hint", "")
        if reasoning_hint:
            with st.expander("💭 Reasoning"):
                st.markdown(reasoning_hint)

        relevant_functions = message.get("relevant_functions", [])
        relevant_types = message.get("relevant_types", [])
        if relevant_functions:
            with st.expander(f"🔧 Relevant Functions ({len(relevant_functions)})"):
                for func in relevant_functions:
                    st.markdown(f"- `{func}`")
        if relevant_types:
            with st.expander(f"📦 Relevant Types ({len(relevant_types)})"):
                for t in relevant_types:
                    st.markdown(f"- `{t}`")

# ── Async query polling ─────────────────────────────────────────────────────
@fragment(run_every=1.0)
def poll_query_task():
    """Poll for query results and render them progressively.

    Wrapped in @fragment(run_every=1.0) so it re-executes automatically at
    1-second intervals while task_started=True. Progress indicators and
    completed results are rendered inline within the fragment scope — the
    sidebar and message rendering loop remain stable. When the task completes
    or fails, task_started is set to False and the fragment stops rerunning.
    """
    if not st.session_state.get("task_started", False):
        return

    task_id = st.session_state.get("active_task_id")
    if not task_id:
        return

    params = st.session_state.get("active_query_params", {})
    token = st.session_state.token

    logger = logging.getLogger(__name__)
    logger.info("Polling task %s (messages in state: %d)", task_id, len(st.session_state.messages))

    # Initialize dedup tracking for this fragment's poll cycle.
    # Reset when a new task starts so old pair_keys don't accumulate.
    if "rendered_backends" not in st.session_state:
        st.session_state.rendered_backends = set()
    if st.session_state.get("rendered_backends_task_id") != task_id:
        st.session_state.rendered_backends = set()
        st.session_state.rendered_backends_task_id = task_id

    # Poll the backend
    result = async_query_poll(API_BASE_URL, task_id, token)

    # ── Error handling ──
    if result.get("error"):
        error_type = result["error"]
        if error_type == "task_not_found":
            st.warning("⚠️ Query session expired — please retry")
        elif error_type in ("unauthorized", "forbidden"):
            st.error("🔒 Authentication error — please log in again")
        elif error_type in ("connection_error", "timeout"):
            st.warning("🌐 Connection lost — please check your connection")
            if st.button("🔄 Retry Now", key="retry_btn"):
                st.rerun()
            return  # Don't clear task for retryable errors
        else:
            st.error(f"❌ Query failed: {error_type}")

        # Clean up on non-retryable errors
        st.session_state.task_started = False
        st.session_state.active_task_id = None
        st.session_state.active_query_params = None
        return

    # ── Parse response ──
    status = result.get("status")
    progress = result.get("progress", {})
    resp_results = result.get("results", [])

    _labels = {
        "cosine": "Cosine Similarity",
        "langchain": "LangChain",
        "llamaindex": "LlamaIndex",
        "api_docs": "API Documentation",
    }

    completed_count = sum(
        1 for r in resp_results
        if r.get("answer") and not r.get("error")
    )

    # ── Progress indicators ──
    st.markdown(
        f"### 🔄 Query in progress... "
        f"({completed_count} backend{'s' if completed_count != 1 else ''} complete)"
    )

    for backend_key in sorted(progress.keys()):
        msg = progress[backend_key]
        label = _labels.get(backend_key, backend_key.title())
        if msg and not msg.startswith("completed") and not msg.startswith("failed"):
            st.info(f"⏳ **{label}**: {msg}")

    # ── Progressive rendering ──
    backend_order = {"cosine": 0, "langchain": 1, "llamaindex": 2, "api_docs": 3}
    sorted_results = sorted(
        resp_results,
        key=lambda r: backend_order.get(r.get("backend", ""), 99),
    )

    for r in sorted_results:
        backend_name = r.get("backend", "unknown")
        label = _labels.get(backend_name, backend_name.title())
        avatar = AVATARS.get(backend_name)
        include_citations = params.get("include_citations", True)
        pair_key = f"{task_id}_{backend_name}"

        if r.get("error"):
            logger.info("Backend %s returned error: %s", backend_name, r["error"])
            st.error(f"❌ **{label}** — {r['error']}")
            if pair_key not in st.session_state.rendered_backends:
                st.session_state.rendered_backends.add(pair_key)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error: {r['error']}",
                    "sources": [],
                    "rag_type": backend_name,
                    "include_citations": include_citations,
                })
        elif r.get("answer"):
            answer_text = r["answer"]
            logger.info(
                "Rendering %s answer (len=%d, preview=%s)",
                backend_name, len(answer_text), answer_text[:80],
            )

            if pair_key not in st.session_state.rendered_backends:
                st.session_state.rendered_backends.add(pair_key)
                sources = r.get("sources", [])
                msg_entry = {
                    "role": "assistant",
                    "content": answer_text,
                    "sources": sources,
                    "rag_type": backend_name,
                    "include_citations": include_citations,
                }
                # API docs extra fields
                if backend_name == "api_docs":
                    msg_entry["reasoning_hint"] = r.get("reasoning_hint", "")
                    msg_entry["confidence"] = r.get("confidence", 0.0)
                    msg_entry["relevant_functions"] = r.get("relevant_functions", [])
                    msg_entry["relevant_types"] = r.get("relevant_types", [])
                st.session_state.messages.append(msg_entry)
                logger.info(
                    "Persisted %s answer to session state (total messages: %d)",
                    backend_name, len(st.session_state.messages),
                )

                # Render inline
                with st.chat_message("assistant", avatar=avatar):
                    rendered_content = answer_text
                    if label:
                        rendered_content = f"**{label}**\n\n{rendered_content}"
                    st.markdown(
                        strip_markdown_formatting(rendered_content, include_citations)
                    )

                if sources:
                    with st.expander(f"📚 Sources ({len(sources)})"):
                        for s in sources:
                            st.caption(s.get("content", "")[:200] + "...")
        else:
            logger.warning(
                "Backend %s result has no answer and no error — skipping",
                backend_name,
            )

    # ── Timeout guard (120s) ──
    created_at = result.get("created_at", 0)
    if (
        created_at
        and (time.time() - created_at) > 120
        and status not in ("completed", "failed")
    ):
        st.error("⏰ Query timed out after 120 seconds")
        st.session_state.task_started = False
        st.session_state.active_task_id = None
        st.session_state.active_query_params = None
        return

    # ── Completion states ──
    if status == "completed":
        logger.info(
            "Task %s completed — messages in state: %d",
            task_id, len(st.session_state.messages),
        )
        for mi, m in enumerate(st.session_state.messages):
            logger.info(
                "  Message[%d] role=%s rag_type=%s content_len=%d",
                mi, m.get("role"), m.get("rag_type", ""), len(m.get("content", "")),
            )

        st.session_state.task_started = False
        st.session_state.active_task_id = None
        st.session_state.active_query_params = None
        st.rerun()
        return
    elif status == "failed":
        error_msg = result.get("error", "Unknown error")
        all_errors = [
            f"{r.get('backend', '?')}: {r['error']}"
            for r in resp_results
            if r.get("error")
        ]
        detailed = "; ".join(all_errors) if all_errors else error_msg
        st.error(f"❌ Query failed: {detailed}")
        st.session_state.task_started = False
        st.session_state.active_task_id = None
        st.session_state.active_query_params = None
    else:
        # Still running — fragment auto-reruns at 1s intervals.
        return




# ── Chat input ──
_chat_disabled = (
    not st.session_state.get("models_ready", False)
    or st.session_state.get("task_started", False)
)
if prompt := st.chat_input(
    "Ask a question...",
    key="chat_input",
    disabled=_chat_disabled,
):
    if not selected_doc_ids:
        st.error("Please select a document")
    else:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "sources": [],
        })
        render_message("user", prompt)

        if not selected_rags and not use_api_docs:
            st.error("Please select at least one RAG implementation")
            st.session_state.messages.pop()
        else:
            params = {
                "temperature": st.session_state.get("rag_temperature", 0.5),
                "max_tokens": st.session_state.get("rag_max_tokens", 600),
                "top_k": st.session_state.get("rag_top_k", 5),
                "prompt_sources": st.session_state.get("rag_prompt_sources", 3),
                "response_length": st.session_state.get("rag_response_length", "normal"),
                "include_citations": st.session_state.get("rag_include_citations", True),
                "clean_response": st.session_state.get("rag_clean_response", False),
            }

            token = st.session_state.token
            backends = selected_rags.copy()

            with st.spinner("Creating query..."):
                start_result = async_query_start(
                    API_BASE_URL,
                    prompt,
                    selected_doc_ids,
                    token,
                    params={
                        **params,
                        "backends": backends,
                        "enable_docs": use_api_docs and len(api_doc_ids) > 0,
                    },
                )

            if "error" in start_result:
                error_msg = start_result["error"]
                if error_msg == "unauthorized":
                    st.error("🔒 Session expired. Please log in again.")
                else:
                    st.error(f"❌ Failed to start query: {error_msg}")
                st.session_state.messages.pop()
            else:
                # Store task info for polling
                st.session_state.active_task_id = start_result["task_id"]
                st.session_state.active_query_params = params
                st.session_state.task_started = True

                # Record question in history
                prompt_stripped = prompt.strip()
                if prompt_stripped and (
                    not st.session_state.question_history
                    or st.session_state.question_history[0] != prompt_stripped
                ):
                    st.session_state.question_history.insert(0, prompt_stripped)
                    if len(st.session_state.question_history) > 200:
                        st.session_state.question_history = (
                            st.session_state.question_history[:200]
                        )

                st.rerun()

# Execute fragment in page flow
poll_query_task()

# Clear chat button (disabled during active query)
if st.button(
    "Clear Chat",
    type="secondary",
    disabled=st.session_state.get("task_started", False),
):
    st.session_state.messages = []
    st.session_state.active_task_id = None
    st.session_state.task_started = False
    st.rerun()

# Compute user_id_hash (first 8 chars of UUID) for localStorage key isolation
_user_id = st.session_state.get("user_id", "")
_user_id_hash = _user_id[:8] if _user_id else ""

# Embed question history data in a hidden div for the JS to read on page load
st.markdown(
    f'<div id="q-history-data" data-history="{html.escape(json.dumps(st.session_state.question_history), quote=True)}" '  # noqa: E501
    f'data-user-hash="{_user_id_hash}"></div>',
    unsafe_allow_html=True,
)

# SECURITY NOTE (unsafe_allow_html vs unsafe_allow_javascript): The hidden div above uses
# st.markdown(unsafe_allow_html=True) to inject a data-only HTML element (no scripts). The JS
# script below uses st.html(unsafe_allow_javascript=True) to execute client-side JavaScript.
# Both inject user-supplied question text via json.dumps() escaping.
# XSS mitigation: json.dumps() produces a properly escaped JSON string, so user text with
# special HTML characters is safely encoded. Questions are user-typed plain text (not rendered
# as markdown/HTML from untrusted sources), further reducing risk.

# Question history arrow-key navigation + auto-focus
st.html("""
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

    function setChatValue(el, value) {
        try {
            el.focus();
            el.select();
            document.execCommand('insertText', false, value);
            return;
        } catch(e) { /* execCommand not supported, fall through */ }
        // Fallback: native setter + InputEvent
        var nativeSetter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value'
        ).set;
        nativeSetter.call(el, value);
        el.dispatchEvent(new InputEvent('input', {
            bubbles: true,
            inputType: 'insertText',
            data: value
        }));
    }

    function findChatInput() {
        var selectors = [
            'textarea[data-testid="stChatInputTextArea"]',
            '.stChatInput textarea',
            'textarea'
        ];
        for (var s = 0; s < selectors.length; s++) {
            var el = document.querySelector(selectors[s]);
            if (el) return el;
        }
        return null;
    }

    function retryFindChatInput(tries) {
        return new Promise(function(resolve) {
            var el = findChatInput();
            if (el) { resolve(el); return; }
            if (tries <= 0) { resolve(null); return; }
            setTimeout(function() {
                resolve(retryFindChatInput(tries - 1));
            }, 200);
        });
    }

    retryFindChatInput(10).then(function(chatInput) {
        if (!chatInput) return;
        // Remove previous handler to avoid stale closure and duplicate listeners
        if (chatInput._qhHandler) {
            chatInput.removeEventListener('keydown', chatInput._qhHandler);
        }
        var handler = function(e) {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (history.length === 0) return;

                if (historyIndex === -1) {
                    // First press: save current draft
                    savedDraft = chatInput.value;
                }

                if (historyIndex < history.length - 1) {
                    historyIndex++;
                    setChatValue(chatInput, history[historyIndex]);
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
                    setChatValue(chatInput, savedDraft);
                } else {
                    setChatValue(chatInput, history[historyIndex]);
                }
                chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
            }
        };
        chatInput._qhHandler = handler;
        chatInput.addEventListener('keydown', handler);
    });

    // Auto-focus the chat input
    setTimeout(function() {
        var chatInput = findChatInput();
        if (chatInput) chatInput.focus();
    }, 100);
})();
</script>
""", unsafe_allow_javascript=True)
