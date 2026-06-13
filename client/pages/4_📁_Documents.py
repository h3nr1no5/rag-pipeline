import streamlit as st
import requests
import time

from client.components.auth_guard import auth_guard
from client.components.ai_spinner import ai_spinner
from client.utils.api_client import logout

st.set_page_config(page_title="Documents - RAG Pipeline", page_icon="📁")

API_BASE_URL = "http://localhost:8000/api/v1"

auth_guard()

st.title("📁 Document Management")

headers = {"Authorization": f"Bearer {st.session_state.token}"}

try:
    models_response = requests.get(f"{API_BASE_URL}/health/models", timeout=30)
    if models_response.status_code == 200:
        models_data = models_response.json()
        all_ready = models_data.get("all_ready", False)
        llm_info = models_data.get("llm", {})
        embedder_info = models_data.get("embedder", {})
        
        if all_ready:
            st.success("✅ AI models ready")
        else:
            with st.container():
                st.info("🔄 Loading AI models...")
                
                llm_status = llm_info.get("status", "")
                llm_model = llm_info.get("model", "")
                llm_progress = llm_info.get("progress", "")
                
                embedder_status = embedder_info.get("status", "")
                embedder_model = embedder_info.get("model", "")
                embedder_progress = embedder_info.get("progress", "")
                
                if llm_status == "ready":
                    st.caption(f"🤖 LLM: {llm_model or 'Ready'}")
                elif llm_status == "downloading":
                    st.caption(f"🤖 LLM: {llm_progress or 'Downloading...'}")
                else:
                    st.caption(f"🤖 LLM: {llm_progress or llm_status}")
                
                if embedder_status == "ready":
                    st.caption(f"🧬 Embedder: {embedder_model or 'Ready'}")
                elif embedder_status == "downloading":
                    st.caption(f"🧬 Embedder: {embedder_progress or 'Downloading...'}")
                else:
                    st.caption(f"🧬 Embedder: {embedder_progress or embedder_status}")
except Exception:
    pass


def get_document_status(doc_id: str) -> dict:
    try:
        response = requests.get(
            f"{API_BASE_URL}/documents/{doc_id}/status",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None


def format_bytes(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


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


def wait_for_processing(doc_id: str, max_wait: int = 120) -> dict:
    progress_bar = st.progress(0)
    status_text = st.empty()
    details_text = st.empty()
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        status = get_document_status(doc_id)
        
        if status:
            doc_status = status.get("status", "unknown")
            step = status.get("processing_step", "unknown")
            message = status.get("processing_message", "")
            total_chars = status.get("total_chars", 0)
            processed = status.get("processed_chars", 0)
            chunk_count = status.get("chunk_count", 0)
            
            emoji = get_step_emoji(step)
            
            if doc_status == "completed":
                progress_bar.progress(100)
                status_text.success(f"✅ {message}")
                details_text.empty()
                return status
            elif doc_status == "failed":
                progress_bar.progress(0)
                status_text.error(f"❌ {message}")
                details_text.error(f"Error: {status.get('error_message', 'Unknown error')}")
                return status
            elif doc_status == "processing":
                if total_chars > 0:
                    progress = min(int((processed / total_chars) * 100), 100)
                    progress_bar.progress(progress)
                else:
                    progress_bar.progress(50)
                
                status_text.info(f"{emoji} **{step.upper()}** - {message}")
                
                details = []
                if total_chars > 0:
                    details.append(f"📊 {processed:,} / {total_chars:,} characters")
                if chunk_count > 0:
                    details.append(f"📝 {chunk_count} chunks created")
                if details:
                    details_text.caption(" | ".join(details))
            elif doc_status == "pending":
                progress_bar.progress(5)
                status_text.warning("⏳ Document queued for processing...")
        else:
            status_text.warning("⚠️ Connecting to server...")
        
        time.sleep(1)
    
    progress_bar.progress(50)
    status_text.warning("⏱️ Processing is taking longer than expected...")
    details_text.info("You can monitor progress from the document list below.")
    return None


with st.sidebar:
    st.title("Upload New Document")
    
    strategies_response = requests.get(f"{API_BASE_URL}/strategies", headers=headers)
    strategies = strategies_response.json() if strategies_response.status_code == 200 else []
    
    if not strategies:
        st.warning("Could not load strategies. Using default.")
        strategy_names = {"Default": "default"}
    else:
        strategy_names = {s["name"]: s["id"] for s in strategies}
    
    selected_strategy = st.selectbox(
        "Chunking Strategy",
        options=list(strategy_names.keys()),
        index=0,
    )
    
    selected_strategy_id = strategy_names[selected_strategy]
    
    strategy_info = next((s for s in strategies if s["id"] == selected_strategy_id), None)
    if strategy_info:
        st.caption(f"📏 Size: {strategy_info.get('chunk_size', 500)} chars")
        st.caption(f"🔁 Overlap: {strategy_info.get('chunk_overlap', 50)} chars")
    
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=["pdf", "docx", "txt", "md", "yaml", "yml", "json"],
        help="Supported: PDF, DOCX, TXT, MD, YAML, JSON (OpenAPI)",
    )
    
    if uploaded_file:
        st.caption(f"📄 {uploaded_file.name}")
        st.caption(f"📦 {format_bytes(uploaded_file.size)}")
    
    if st.button("Upload", use_container_width=True, type="primary"):
        if uploaded_file:
            with ai_spinner("Uploading..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    data = {"strategy_id": selected_strategy_id}
                    
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
                    else:
                        st.error(f"Upload failed: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
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
            cols = st.columns([3, 1, 1, 1, 1])
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

            cols = st.columns([3, 1, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{doc['title']}{embedded_badge}**")
                st.caption(f"📄 {doc['doc_type'].upper()} | {format_bytes(doc.get('file_size', 0))}")
            with cols[1]:
                status_data = get_document_status(doc["id"])
                if status_data and doc_status == "processing":
                    step = status_data.get("processing_step", "")
                    message = status_data.get("processing_message", "")
                    emoji = get_step_emoji(step)
                    st.markdown(f"{emoji} {message[:20]}...")
                else:
                    st.markdown(f"{emoji} {label}")
            with cols[2]:
                st.markdown(f"`{doc['chunk_count']}`")
            with cols[3]:
                st.markdown(f"`{doc['chunking_strategy']['name']}`")
            
            with cols[4]:
                col_actions = st.columns([1, 1])
                with col_actions[0]:
                    if st.button("🗑️", key=f"delete_{doc['id']}", help="Delete document", use_container_width=True):
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
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Status:** {doc_status}")
                    st.markdown(f"**Chunks:** {doc['chunk_count']}")
                    st.markdown(f"**Strategy:** {doc['chunking_strategy']['name']}")
                    st.markdown(f"**Embedded:** {'✅ Yes' if doc.get('embedded') else '❌ No'}")
                with col2:
                    st.markdown(f"**Type:** {doc['doc_type']}")
                    st.markdown(f"**Size:** {format_bytes(doc.get('file_size', 0))}")
                    if doc.get("is_api_doc"):
                        st.badge("API Document", icon="🔌")
                    if doc.get("embedded"):
                        if st.button("🔄 Clear & Reprocess", key=f"reprocess_{doc['id']}", help="Clear embeddings and reprocess"):
                            clear_response = requests.post(
                                f"{API_BASE_URL}/documents/{doc['id']}/clear-embeddings",
                                headers=headers
                            )
                            if clear_response.status_code == 200:
                                st.success("Embeddings cleared. Reprocessing...")
                                reprocess_response = requests.post(
                                    f"{API_BASE_URL}/documents/{doc['id']}/reprocess",
                                    headers=headers
                                )
                                if reprocess_response.status_code == 200:
                                    st.rerun()
                                else:
                                    st.error("Failed to reprocess")
                            else:
                                st.error(f"Failed to clear: {clear_response.json().get('detail', 'Unknown error')}")
            
            st.divider()
    else:
        st.error("Failed to load documents")
except Exception as e:
    st.error(f"Error loading documents: {str(e)}")
