import json
import os
import time

import requests
import streamlit as st

from client.components.ai_spinner import ai_spinner
from client.components.auth_guard import auth_guard
from client.components.model_status import model_status_banner
from client.utils.api_client import logout

st.set_page_config(page_title="Documents - RAG Pipeline", page_icon="📁")

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")

auth_guard()

st.title("📁 Document Management")

headers = {"Authorization": f"Bearer {st.session_state.token}"}

# Show model status banner using shared component
model_status = model_status_banner(API_BASE_URL, headers)

if model_status["all_ready"]:
    st.success("✅ AI models ready")


def get_document_status(doc_id: str) -> dict:
    try:
        response = requests.get(
            f"{API_BASE_URL}/documents/{doc_id}/status",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def format_bytes(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

PARAM_FILE = "./data/chunking_params.json"

def load_chunking_params():
    if os.path.exists(PARAM_FILE):
        try:
            with open(PARAM_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_chunking_params(params):
    os.makedirs(os.path.dirname(PARAM_FILE), exist_ok=True)
    with open(PARAM_FILE, "w") as f:
        json.dump(params, f)


def get_step_emoji(step: str) -> str:
    emojis = {
        "parsing": "📄",
        "chunking": "✂️",
        "saving": "💾",
        "completed": "✅",
        "failed": "❌",
        "pending": "⏳",
    }
    return emojis.get(step, "🔄")


def render_stage_bar(label: str, progress_value: int, detail: str | None = None, is_active: bool = False):  # noqa: E501
    """Render a single compact stage progress bar."""
    cols = st.columns([1, 4])
    with cols[0]:
        st.caption(label)
    with cols[1]:
        if progress_value == 100:
            st.progress(1.0, text="✅" if not detail else f"✅ {detail}")
        elif progress_value == 0 and is_active:
            st.progress(0, text="🔄 in progress...")
        elif progress_value == 0:
            st.progress(0, text="⏳ waiting")
        else:
            detail_text = f"{progress_value}%" + (f" ({detail})" if detail else "")
            st.progress(progress_value / 100, text=detail_text)


def wait_for_processing(doc_id: str, max_wait: int = 120) -> dict:
    status_text = st.empty()
    stage_bars = st.empty()
    start_time = time.time()

    while time.time() - start_time < max_wait:
        status = get_document_status(doc_id)

        if status:
            doc_status = status.get("status", "unknown")
            step = status.get("processing_step", "unknown")
            message = status.get("processing_message", "")
            parsing_progress = status.get("parsing_progress", 0)
            chunking_progress = status.get("chunking_progress", 0)
            saving_progress = status.get("saving_progress", 0)
            saved_chunks = status.get("saved_chunks", 0)
            chunk_count = status.get("chunk_count", 0)

            if doc_status == "completed":
                status_text.success(f"✅ {message}")
                stage_bars.empty()
                return status
            elif doc_status == "failed":
                status_text.error(f"❌ {message}")
                stage_bars.error(f"Error: {status.get('error_message', 'Unknown error')}")
                return status
            elif doc_status == "processing":
                emoji = get_step_emoji(step)
                status_text.info(f"{emoji} **{step.upper()}** - {message}")

                with stage_bars.container():
                    # Parsing bar
                    parse_active = parsing_progress == 0 and step == "parsing"
                    st.caption(f"📄 Parsing {'✅' if parsing_progress == 100 else ('🔄' if parse_active else '⏳')}")  # noqa: E501
                    st.progress(parsing_progress / 100 if parsing_progress > 0 else 0)

                    # Chunking bar
                    chunk_active = chunking_progress == 0 and step == "chunking"
                    st.caption(f"✂️ Chunking {'✅' if chunking_progress == 100 else ('🔄' if chunk_active else '⏳')}")  # noqa: E501
                    st.progress(chunking_progress / 100 if chunking_progress > 0 else 0)

                    # Saving bar
                    save_active = step == "saving"
                    saving_detail = f" ({saved_chunks}/{chunk_count} chunks)" if (saving_progress > 0 and saving_progress < 100) else ""  # noqa: E501
                    st.caption(f"🧠 Embed + Save {'✅' if saving_progress == 100 else ('🔄' + saving_detail if save_active else '⏳')}")  # noqa: E501
                    st.progress(saving_progress / 100 if saving_progress > 0 else 0)

                    # Additional info
                    details = []
                    if chunk_count > 0:
                        details.append(f"📝 {chunk_count} chunks total")
                    if details:
                        st.caption(" | ".join(details))
            elif doc_status == "pending":
                status_text.warning("⏳ Document queued for processing...")
                stage_bars.empty()
        else:
            status_text.warning("⚠️ Connecting to server...")

        time.sleep(1)

    status_text.warning("⏱️ Processing is taking longer than expected...")
    return None


_embedder_ready = model_status.get("embedder_ready", False)

with st.sidebar:
    st.title("Upload New Document")

    try:
        strategies_response = requests.get(f"{API_BASE_URL}/strategies", headers=headers)
        strategies = strategies_response.json() if strategies_response.status_code == 200 else []
    except requests.RequestException:
        strategies = []

    if not strategies:
        st.warning("Could not load strategies. Using Recursive.")
        strategy_names = {"Recursive": "recursive"}
    else:
        strategy_names = {s["name"]: s["id"] for s in strategies}

    selected_strategy = st.selectbox(
        "Chunking Strategy",
        options=list(strategy_names.keys()),
        index=0,
    )

    selected_strategy_id = strategy_names[selected_strategy]

    # Load saved chunking params
    saved_chunking_params = load_chunking_params()

    strategy_info = next((s for s in strategies if s["id"] == selected_strategy_id), None)
    is_api_docs = strategy_info and strategy_info.get("engine_type") == "api-docs"

    # Track strategy changes to reset form fields
    if "last_strategy_id" not in st.session_state:
        st.session_state.last_strategy_id = None

    # When strategy changes, reset to saved defaults or strategy defaults
    if st.session_state.last_strategy_id != selected_strategy_id:
        st.session_state.last_strategy_id = selected_strategy_id
        strategy_defaults = saved_chunking_params.get(selected_strategy_id, {})
        if not strategy_defaults and strategy_info:
            strategy_defaults = {
                "chunk_size": strategy_info.get("chunk_size", 500),
                "chunk_overlap": strategy_info.get("chunk_overlap", 50),
                "separators": json.dumps(strategy_info.get("separators", ["\\n\\n", "\\n", ". "])),
                "use_hyperlinks": strategy_info.get("use_hyperlinks", False),
            }
        if strategy_defaults:
            st.session_state["chunk_size_slider"] = max(50, strategy_defaults.get("chunk_size", 500))  # noqa: E501
            st.session_state["chunk_overlap_slider"] = strategy_defaults.get("chunk_overlap", 50)
            sep_val = strategy_defaults.get("separators", '["\\n\\n", "\\n", ". "]')
            if isinstance(sep_val, list):
                sep_val = json.dumps(sep_val)
            st.session_state["separators_input"] = sep_val
            st.session_state["use_hyperlinks_checkbox"] = strategy_defaults.get("use_hyperlinks", False)  # noqa: E501
        st.rerun()

    # Initialize session state defaults for first load
    if "chunk_size_slider" not in st.session_state:
        default_cs = saved_chunking_params.get(selected_strategy_id, {}).get("chunk_size", strategy_info.get("chunk_size", 500) if strategy_info else 500)  # noqa: E501
        st.session_state.chunk_size_slider = max(50, default_cs)
    if "chunk_overlap_slider" not in st.session_state:
        default_co = saved_chunking_params.get(selected_strategy_id, {}).get("chunk_overlap", strategy_info.get("chunk_overlap", 50) if strategy_info else 50)  # noqa: E501
        st.session_state.chunk_overlap_slider = default_co
    if "separators_input" not in st.session_state:
        default_sep = saved_chunking_params.get(selected_strategy_id, {}).get("separators", json.dumps(strategy_info.get("separators", ["\\n\\n", "\\n", ". "]) if strategy_info else ["\\n\\n", "\\n", ". "]))  # noqa: E501
        if isinstance(default_sep, list):
            default_sep = json.dumps(default_sep)
        st.session_state.separators_input = default_sep
    if "use_hyperlinks_checkbox" not in st.session_state:
        default_hl = saved_chunking_params.get(selected_strategy_id, {}).get("use_hyperlinks", strategy_info.get("use_hyperlinks", False) if strategy_info else False)  # noqa: E501
        st.session_state.use_hyperlinks_checkbox = default_hl

    st.caption("### Chunking Parameters")

    chunk_size = st.slider(
        "Chunk Size (tokens)",
        min_value=50,
        max_value=2000,
        key="chunk_size_slider",
        step=50,
        disabled=is_api_docs,
        help="Maximum chunk size in tokens" + (" (not used by API documentation strategy)" if is_api_docs else ""),  # noqa: E501
    )
    chunk_overlap = st.slider(
        "Chunk Overlap (tokens)",
        min_value=0,
        max_value=500,
        key="chunk_overlap_slider",
        step=10,
        disabled=is_api_docs,
        help="Overlap between adjacent chunks in tokens" + (" (not used by API documentation strategy)" if is_api_docs else ""),  # noqa: E501
    )
    separators_str = st.text_input(
        "Separators (JSON array)",
        key="separators_input",
        disabled=is_api_docs,
        help='JSON array of separator strings, e.g., ["\\n\\n", "\\n", ". "]' + (" (not used by API documentation strategy)" if is_api_docs else ""),  # noqa: E501
    )
    use_hyperlinks = st.checkbox(
        "Use Hyperlinks",
        key="use_hyperlinks_checkbox",
        disabled=is_api_docs,
        help="Enable hyperlink-aware chunking" + (" (not used by API documentation strategy)" if is_api_docs else ""),  # noqa: E501
    )

    # Parse separators with safety (skip when disabled since value is not used)
    if is_api_docs:
        parsed_separators = ["\n\n", "\n", ". "]
    else:
        try:
            parsed_separators = json.loads(separators_str)
            if not isinstance(parsed_separators, list) or not all(isinstance(s, str) for s in parsed_separators):  # noqa: E501
                st.error("Separators must be a JSON array of strings")
                parsed_separators = strategy_info.get("separators", ["\\n\\n", "\\n", ". "]) if strategy_info else ["\\n\\n", "\\n", ". "]  # noqa: E501
        except (json.JSONDecodeError, TypeError):
            st.error("Invalid JSON in separators")
            parsed_separators = strategy_info.get("separators", ["\\n\\n", "\\n", ". "]) if strategy_info else ["\\n\\n", "\\n", ". "]  # noqa: E501

    if st.button("Save as Defaults", use_container_width=True, disabled=is_api_docs):
        save_chunking_params({
            selected_strategy_id: {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "separators": json.dumps(parsed_separators),
                "use_hyperlinks": use_hyperlinks,
            }
        })
        st.success("Defaults saved!")

    uploaded_file = st.file_uploader(
        "Choose a file",
        type=["pdf", "docx", "txt", "md", "yaml", "yml", "json"],
        disabled=not _embedder_ready,
        help="Upload documents" if _embedder_ready else "Embedder model is loading — please wait",
    )

    if uploaded_file:
        st.caption(f"📄 {uploaded_file.name}")
        st.caption(f"📦 {format_bytes(uploaded_file.size)}")

    if st.button("Upload", use_container_width=True, type="primary", disabled=not _embedder_ready):
        if uploaded_file:
            with ai_spinner("Uploading..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}  # noqa: E501
                    data = {"strategy_id": selected_strategy_id}
                    data["chunk_size"] = str(chunk_size)
                    data["chunk_overlap"] = str(chunk_overlap)
                    data["separators"] = json.dumps(parsed_separators)
                    data["use_hyperlinks"] = str(use_hyperlinks).lower()

                    response = requests.post(
                        f"{API_BASE_URL}/documents",
                        files=files,
                        data=data,
                        headers={"Authorization": f"Bearer {st.session_state.token}"}
                    )

                    if response.status_code == 201:
                        result = response.json()
                        st.success("📤 Upload complete! Processing started...")

                        wait_for_processing(result["id"])
                        st.rerun()
                    elif response.status_code == 503:
                        st.error("Model 'embedder' is not ready — please wait and try again")
                    else:
                        st.error(f"Upload failed: {response.text}")
                except Exception as e:
                    st.error(f"Error: {e!s}")
        else:
            st.warning("Please select a file")

    st.divider()

    if st.button("Logout", use_container_width=True):
        logout()
        st.rerun()

st.subheader("Your Documents")

try:
    response = requests.get(f"{API_BASE_URL}/documents", headers=headers)
    if response.status_code == 200:
        data = response.json()
        documents = data.get("documents", [])

        if not documents:
            st.info("No documents uploaded yet. Upload your first document using the sidebar.")
        else:
            cols = st.columns([3, 2, 1, 1, 1])
            with cols[0]:
                st.markdown("**Document**")
            with cols[1]:
                st.markdown("**Status**")
            with cols[2]:
                st.markdown("**Chunks**")
            with cols[3]:
                st.markdown("**Strategy**")
            with cols[4]:
                st.markdown("**Action**")

            st.divider()

        for doc in documents:
            # show embedded badge in document title
            embedded_badge = " 🧬 Embedded" if doc.get("embedded") else ""
            doc_status = doc.get("status", "unknown")
            status_config = {
                "completed": ("✅", "Completed", "success"),
                "pending": ("⏳", "Pending", "info"),
                "processing": ("🔄", "Processing", "info"),
                "failed": ("❌", "Failed", "error"),
            }
            emoji, label, _ = status_config.get(doc_status, ("⚪", doc_status.title(), "off"))

            cols = st.columns([3, 2, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{doc['title']}{embedded_badge}**")
                st.caption(f"📄 {doc['doc_type'].upper()} | {format_bytes(doc.get('file_size', 0))}")  # noqa: E501
            with cols[1]:
                if doc_status == "processing":
                    # Use progress fields from the list response directly (no N+1 HTTP call)
                    parsing_progress = doc.get("parsing_progress", 0)
                    chunking_progress = doc.get("chunking_progress", 0)
                    saving_progress = doc.get("saving_progress", 0)
                    saved_chunks = doc.get("saved_chunks", 0)
                    chunk_count = doc.get("chunk_count", 0)

                    # Infer active processing stage from progress values
                    if parsing_progress < 100:
                        active_stage = "parsing"
                    elif chunking_progress < 100:
                        active_stage = "chunking"
                    elif saving_progress < 100:
                        active_stage = "saving"
                    else:
                        active_stage = "completed"

                    with st.container():
                        render_stage_bar("📄 Parse", parsing_progress, is_active=(active_stage == "parsing"))  # noqa: E501
                        render_stage_bar("✂️ Chunk", chunking_progress, is_active=(active_stage == "chunking"))  # noqa: E501
                        saving_detail = f"{saved_chunks}/{chunk_count} chunks" if saving_progress > 0 and saving_progress < 100 else None  # noqa: E501
                        render_stage_bar("🧠 Save", saving_progress, detail=saving_detail, is_active=(active_stage == "saving"))  # noqa: E501
                else:
                    st.markdown(f"{emoji} {label}")
            with cols[2]:
                st.markdown(f"`{doc['chunk_count']}`")
            with cols[3]:
                st.markdown(f"`{doc['chunking_strategy']['name']}`")

            with cols[4]:
                col_actions = st.columns([1, 1])
                with col_actions[0]:
                    if st.button("🗑️", key=f"delete_{doc['id']}", help="Delete document", use_container_width=True):  # noqa: E501
                        delete_response = requests.delete(
                            f"{API_BASE_URL}/documents/{doc['id']}",
                            headers=headers
                        )
                        if delete_response.status_code == 204:
                            st.success("Deleted")
                            st.rerun()
                        else:
                            st.error("Failed to delete")

            with st.expander("📋 View Details"):
                st.markdown(f"**UUID:** `{doc['id']}`")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Status:** {doc_status}")
                    st.markdown(f"**Chunks:** {doc['chunk_count']}")
                    st.markdown(f"**Strategy:** {doc['chunking_strategy']['name']}")
                    st.markdown(f"**Embedded:** {'✅ Yes' if doc.get('embedded') else '❌ No'}")
                with col2:
                    st.markdown(f"**Type:** {doc['doc_type']}")
                    st.markdown(f"**Size:** {format_bytes(doc.get('file_size', 0))}")
                    if doc.get("embedded"):
                        if st.button("🔄 Clear & Reprocess", key=f"reprocess_{doc['id']}", help="Clear embeddings and reprocess"):  # noqa: E501
                            clear_response = requests.post(
                                f"{API_BASE_URL}/documents/{doc['id']}/clear-embeddings",
                                headers=headers
                            )
                            if clear_response.status_code == 200:
                                st.success("Embeddings cleared. Reprocessing...")
                                reprocess_response = requests.post(
                                    f"{API_BASE_URL}/documents/{doc['id']}/reprocess",
                                    data={
                                        "chunk_size": str(chunk_size),
                                        "chunk_overlap": str(chunk_overlap),
                                        "separators": json.dumps(parsed_separators),
                                        "use_hyperlinks": str(use_hyperlinks).lower(),
                                    },
                                    headers=headers
                                )
                                if reprocess_response.status_code == 200:
                                    st.rerun()
                                else:
                                    st.error("Failed to reprocess")
                            else:
                                st.error(f"Failed to clear: {clear_response.json().get('detail', 'Unknown error')}")  # noqa: E501
            st.divider()

        # Auto-refresh while documents are processing
        processing_docs = [d for d in documents if d.get("status") == "processing"]
        if processing_docs:
            time.sleep(2)
            st.rerun()

    else:
        st.error("Failed to load documents")
except Exception as e:
    st.error(f"Error loading documents: {e!s}")
