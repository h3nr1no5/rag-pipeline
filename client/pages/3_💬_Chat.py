import streamlit as st
import requests
import time

from client.components.auth_guard import auth_guard
from client.components.chat_message import render_message
from client.utils.api_client import logout
from client.utils.query import (
    stream_query_with_placeholder,
    stream_query_langchain_with_placeholder,
    stream_query_langchain,
)

st.set_page_config(page_title="Chat - RAG Pipeline", page_icon="💬")

API_BASE_URL = "http://localhost:8000/api/v1"

# Custom CSS for enhanced comparison UI
st.markdown("""
<style>
    /* Enhanced comparison container styling */
    .comparison-wrapper {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border-radius: 12px;
        padding: 20px;
        margin: 16px 0;
    }
    
    /* Column card styling - Current RAG (Blue theme) */
    .rag-card-current {
        background: #ffffff;
        border-left: 4px solid #3b82f6;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        margin-bottom: 16px;
    }
    
    /* Column card styling - LangChain RAG (Purple theme) */
    .rag-card-langchain {
        background: #ffffff;
        border-left: 4px solid #8b5cf6;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        margin-bottom: 16px;
    }
    
    /* Header badges */
    .rag-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        border-radius: 8px;
        font-weight: 600;
        font-size: 14px;
        margin-bottom: 12px;
    }
    
    .rag-badge-current {
        background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
        color: #1e40af;
        border: 1px solid #93c5fd;
    }
    
    .rag-badge-langchain {
        background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
        color: #5b21b6;
        border: 1px solid #c4b5fd;
    }
    
    /* Enhanced expander styling */
    .styled-expander {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        margin-top: 12px;
    }
    
    .styled-expander .streamlit-expanderHeader {
        background: #f1f5f9;
        border-radius: 8px;
        font-weight: 500;
        color: #475569;
    }
    
    .styled-expander .streamlit-expanderHeader:hover {
        background: #e2e8f0;
    }
    
    /* Source item styling */
    .source-item {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px;
        margin-bottom: 8px;
    }
    
    .source-label {
        font-weight: 600;
        color: #334155;
        font-size: 13px;
    }
    
    /* ========== ENHANCED THINKING ANIMATIONS (ChatGPT/Claude Style) ========== */
    
    /* AI Thinking Bubble - Main Container */
    .ai-thinking-container {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px 20px;
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border-radius: 16px;
        margin: 8px 0;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    }
    
    /* Glowing AI icon */
    .ai-thinking-icon {
        width: 36px;
        height: 36px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        flex-shrink: 0;
        position: relative;
        color: white;
    }
    
    .ai-thinking-icon.current {
        background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
    }
    
    .ai-thinking-icon.langchain {
        background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%);
        box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
    }
    
    .ai-thinking-icon.single {
        background: linear-gradient(135deg, #6366f1 0%, #818cf8 100%);
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    }
    
    /* Pulsing glow animation */
    @keyframes icon-pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.05); }
    }
    
    .ai-thinking-icon::after {
        content: '';
        position: absolute;
        inset: -3px;
        border-radius: 14px;
        background: inherit;
        filter: blur(8px);
        opacity: 0.5;
        z-index: -1;
        animation: icon-pulse 2s infinite ease-in-out;
    }
    
    /* Thinking dots - More fluid and organic */
    .ai-dots-container {
        display: flex;
        align-items: center;
        gap: 6px;
        height: 24px;
    }
    
    @keyframes ai-dot-float {
        0%, 100% { 
            transform: translateY(0) scale(0.8); 
            opacity: 0.4;
        }
        25% { 
            transform: translateY(-3px) scale(1); 
            opacity: 1;
        }
        50% { 
            transform: translateY(-1px) scale(0.9); 
            opacity: 0.7;
        }
        75% { 
            transform: translateY(-4px) scale(1); 
            opacity: 1;
        }
    }
    
    .ai-thinking-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        animation: ai-dot-float 1.4s infinite ease-in-out;
    }
    
    .ai-thinking-dot.current { background: #3b82f6; }
    .ai-thinking-dot.langchain { background: #8b5cf6; }
    .ai-thinking-dot.single { background: #6366f1; }
    
    .ai-thinking-dot:nth-child(1) { animation-delay: 0s; }
    .ai-thinking-dot:nth-child(2) { animation-delay: 0.2s; }
    .ai-thinking-dot:nth-child(3) { animation-delay: 0.4s; }
    .ai-thinking-dot:nth-child(4) { animation-delay: 0.6s; }
    .ai-thinking-dot:nth-child(5) { animation-delay: 0.8s; }
    
    /* Status text */
    .ai-status-text {
        font-size: 14px;
        font-weight: 500;
        color: #475569;
        margin-top: 8px;
    }
    
    /* Progress bar for multi-step */
    .ai-progress-container {
        width: 100%;
        margin-bottom: 16px;
    }
    
    .ai-progress-steps {
        display: flex;
        justify-content: space-between;
        margin-bottom: 8px;
        position: relative;
    }
    
    .ai-progress-step {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        flex: 1;
        position: relative;
        z-index: 1;
    }
    
    .ai-step-indicator {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .ai-step-indicator.current-rag {
        background: #3b82f6;
        color: white;
    }
    
    .ai-step-indicator.langchain-rag {
        background: #e2e8f0;
        color: #94a3b8;
    }
    
    .ai-step-indicator.active {
        box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2);
    }
    
    .ai-step-indicator.completed {
        background: #10b981;
        color: white;
    }
    
    .ai-step-indicator.langchain-rag.active {
        background: #8b5cf6;
        color: white;
        box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.2);
    }
    
    .ai-step-indicator.langchain-rag.completed {
        background: #10b981;
        color: white;
    }
    
    .ai-step-label {
        font-size: 11px;
        color: #64748b;
        text-align: center;
        max-width: 80px;
    }
    
    .ai-step-label.active {
        color: #3b82f6;
        font-weight: 600;
    }
    
    /* Progress line */
    .ai-progress-line {
        position: absolute;
        top: 14px;
        left: 15%;
        right: 15%;
        height: 3px;
        background: #e2e8f0;
        border-radius: 2px;
        z-index: 0;
    }
    
    .ai-progress-fill {
        height: 100%;
        border-radius: 2px;
        transition: width 0.5s ease;
    }
    
    .ai-progress-fill.current {
        background: linear-gradient(90deg, #3b82f6, #60a5fa);
    }
    
    .ai-progress-fill.langchain {
        background: linear-gradient(90deg, #8b5cf6, #a78bfa);
    }
    
    /* Morphing spinner animation */
    @keyframes morph-spin {
        0% { border-radius: 50%; transform: rotate(0deg) scale(1); }
        25% { border-radius: 40% 60% 60% 40%; transform: rotate(90deg) scale(1.1); }
        50% { border-radius: 60% 40% 40% 60%; transform: rotate(180deg) scale(1); }
        75% { border-radius: 40% 60% 60% 40%; transform: rotate(270deg) scale(1.1); }
        100% { border-radius: 50%; transform: rotate(360deg) scale(1); }
    }
    
    /* Legacy loading animations kept for backward compatibility */
    @keyframes thinking-pulse {
        0%, 100% { 
            box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4);
            opacity: 0.6;
        }
        50% { 
            box-shadow: 0 0 0 8px rgba(59, 130, 246, 0);
            opacity: 1;
        }
    }
    
    @keyframes thinking-dot {
        0%, 60%, 100% { 
            transform: translateY(0); 
            opacity: 0.3; 
        }
        30% { 
            transform: translateY(-4px); 
            opacity: 1; 
        }
    }
    
    .thinking-container {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 0;
    }
    
    .thinking-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        animation: thinking-dot 1.2s infinite ease-in-out;
    }
    
    .thinking-dot.current {
        background: #3b82f6;
    }
    
    .thinking-dot.langchain {
        background: #8b5cf6;
    }
    
    .thinking-dot:nth-child(2) { animation-delay: 0.15s; }
    .thinking-dot:nth-child(3) { animation-delay: 0.3s; }
    
    /* Loading bar animation */
    .loading-bar-container {
        width: 100%;
        height: 4px;
        background: #e2e8f0;
        border-radius: 2px;
        margin: 8px 0;
        overflow: hidden;
    }
    
    .loading-bar {
        height: 100%;
        border-radius: 2px;
        animation: loading-slide 1.5s infinite ease-in-out;
    }
    
    .loading-bar.current {
        background: linear-gradient(90deg, #3b82f6, #60a5fa, #3b82f6);
    }
    
    .loading-bar.langchain {
        background: linear-gradient(90deg, #8b5cf6, #a78bfa, #8b5cf6);
    }
    
    @keyframes loading-slide {
        0% { width: 0%; margin-left: 0%; }
        50% { width: 60%; margin-left: 20%; }
        100% { width: 0%; margin-left: 100%; }
    }
    
    /* Status indicators */
    .status-cached {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        color: #059669;
        background: #d1fae5;
        padding: 4px 8px;
        border-radius: 4px;
    }
    
    /* Column spacing */
    .compare-column {
        padding: 8px;
    }
    
    /* Smooth transitions */
    .rag-card-current, .rag-card-langchain {
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    
    .rag-card-current:hover, .rag-card-langchain:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    /* Section header divider */
    .section-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent, #e2e8f0, transparent);
        margin: 12px 0;
    }
    
    /* Source card within expander */
    .source-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px;
        margin-bottom: 8px;
    }
    
    .source-card:last-child {
        margin-bottom: 0;
    }
    
    /* Expander icon rotation */
    .streamlit-expanderHeader svg {
        transition: transform 0.2s ease;
    }
    
    .streamlit-expanderHeader[aria-expanded="true"] svg {
        transform: rotate(90deg);
    }
    
    /* Mobile responsive adjustments */
    @media (max-width: 768px) {
        .rag-badge {
            font-size: 12px;
            padding: 6px 12px;
        }
        
        .rag-card-current, .rag-card-langchain {
            padding: 12px;
        }
    }
</style>
""", unsafe_allow_html=True)

auth_guard()

st.title("💬 Chat with Documents")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "selected_docs" not in st.session_state:
    st.session_state.selected_docs = []

if "chat_initialized" not in st.session_state:
    st.session_state.chat_initialized = True

# Get compare mode default from config
if "compare_mode_enabled" not in st.session_state:
    st.session_state.compare_mode_enabled = True  # Default from .env

headers = {"Authorization": f"Bearer {st.session_state.token}"}

try:
    models_response = requests.get(f"{API_BASE_URL}/health/models", timeout=30)
    if models_response.status_code == 200:
        models_data = models_response.json()
        all_ready = models_data.get("all_ready", False)
        llm_info = models_data.get("llm", {})
        embedder_info = models_data.get("embedder", {})
        
        # Get compare mode default from API
        st.session_state.compare_mode_enabled = models_data.get("compare_mode_default", True)
        
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
                elif llm_status == "not_started":
                    st.caption("🤖 LLM: Pending...")
                else:
                    st.caption(f"🤖 LLM: {llm_progress or llm_status}")
                
                if embedder_status == "ready":
                    st.caption(f"🧬 Embedder: {embedder_model or 'Ready'}")
                elif embedder_status == "downloading":
                    st.caption(f"🧬 Embedder: {embedder_progress or 'Downloading...'}")
                elif embedder_status == "not_loaded":
                    st.caption("🧬 Embedder: Pending...")
                else:
                    st.caption(f"🧬 Embedder: {embedder_progress or embedder_status}")
except Exception:
    pass

try:
    response = requests.get(f"{API_BASE_URL}/documents", headers=headers)
    if response.status_code == 200:
        documents = response.json().get("documents", [])
    else:
        documents = []
except:
    documents = []

doc_options = {doc["title"]: doc["id"] for doc in documents}
display_titles = [f"{doc['title']}{' 🧬 Embedded' if doc.get('embedded') else ''}" for doc in documents]
display_map = {f"{doc['title']}{' 🧬 Embedded' if doc.get('embedded') else ''}": doc['id'] for doc in documents}

if documents:
    st.sidebar.title("📁 Select Documents")
    
    current_selected = st.session_state.get("selected_docs", [])
    valid_selections = [t for t in current_selected if t in display_titles]
    
    current_selected = st.session_state.get("selected_docs", [])
    valid_selections = [t for t in current_selected if t in display_titles]
    
    if not valid_selections:
        embedded_docs = [doc for doc in documents if doc.get("embedded")]
        if embedded_docs:
            valid_selections = [f"{embedded_docs[0]['title']} 🧬 Embedded"]
    
    selected_titles = st.sidebar.multiselect(
        "Choose documents to query:",
        options=display_titles,
        default=valid_selections,
        key="docs_multiselect",
    )
    st.session_state.selected_docs = selected_titles
    selected_doc_ids = [display_map[title] for title in selected_titles if title in display_map]

    # Show current strategy details to help users understand embedding behavior
    if documents:
        first_strategy = documents[0].get("chunking_strategy")
        if first_strategy:
            st.sidebar.subheader("Strategy Details")
            st.sidebar.markdown(f"- Name: {first_strategy.get('name', '')}")
            st.sidebar.markdown(f"- Chunk size: {first_strategy.get('chunk_size', '')}")
            st.sidebar.markdown(f"- Overlap: {first_strategy.get('chunk_overlap', '')}")
            seps = first_strategy.get('separators', [])
            st.sidebar.markdown(f"- Separators: {', '.join(seps)}")
            st.sidebar.markdown(f"- Embedding model: {first_strategy.get('embedding_model', '')}")

    if not selected_doc_ids:
        st.info("👈 Select at least one document from the sidebar to start chatting")
else:
    st.info("No documents uploaded yet. Go to the Documents page to upload some.")
    selected_doc_ids = []

st.sidebar.divider()

# Compare mode toggle
st.sidebar.subheader("⚙️ Settings")
compare_mode = st.sidebar.toggle(
    "🔍 Compare Mode",
    value=st.session_state.compare_mode_enabled,
    help="Show side-by-side comparison: Current RAG (blue) vs LangChain Hybrid RAG (purple)",
)
st.session_state.compare_mode_enabled = compare_mode
if compare_mode:
    st.sidebar.markdown("""
    <div style="display: flex; gap: 8px; align-items: center;">
        <span style="width: 10px; height: 10px; background: #3b82f6; border-radius: 50%;"></span>
        <span style="color: #64748b; font-size: 12px;">Current RAG</span>
        <span style="color: #cbd5e1;">vs</span>
        <span style="width: 10px; height: 10px; background: #8b5cf6; border-radius: 50%;"></span>
        <span style="color: #64748b; font-size: 12px;">LangChain</span>
    </div>
    """, unsafe_allow_html=True)

st.sidebar.divider()

if st.sidebar.button("Logout", use_container_width=True, key="logout_btn"):
    logout()
    st.rerun()


def render_side_by_side(current_response, langchain_response):
    """Render side-by-side comparison of two responses with enhanced styling."""
    
    col1, col2 = st.columns(2, gap="large")
    
    with col1:
        # Current RAG Column - Blue theme
        st.markdown("""
        <div class="rag-badge rag-badge-current">
            <span>📤</span> Current RAG
        </div>
        """, unsafe_allow_html=True)
        
        if current_response.get("cached"):
            st.markdown("""
            <span class="status-cached">📦 Cached Response</span>
            """, unsafe_allow_html=True)
        
        # Card container with blue accent
        st.markdown('<div class="rag-card-current">', unsafe_allow_html=True)
        st.markdown(current_response.get("answer", ""))
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Sources expander - styled
        sources = current_response.get("sources", [])
        if sources:
            with st.expander("📚 View Sources", expanded=False):
                for i, source in enumerate(sources, 1):
                    st.markdown(f"**Source {i}:**")
                    content = source.get("content", "")
                    st.caption(content[:300] + "..." if len(content) > 300 else content)
                    if i < len(sources):
                        st.divider()
    
    with col2:
        # LangChain RAG Column - Purple theme
        st.markdown("""
        <div class="rag-badge rag-badge-langchain">
            <span>🔗</span> LangChain RAG
        </div>
        """, unsafe_allow_html=True)
        
        if langchain_response.get("cached"):
            st.markdown("""
            <span class="status-cached">📦 Cached Response</span>
            """, unsafe_allow_html=True)
        
        # Card container with purple accent
        st.markdown('<div class="rag-card-langchain">', unsafe_allow_html=True)
        st.markdown(langchain_response.get("answer", ""))
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Sources expander - styled
        sources = langchain_response.get("sources", [])
        if sources:
            with st.expander("📚 View Sources", expanded=False):
                for i, source in enumerate(sources, 1):
                    st.markdown(f"**Source {i}:**")
                    content = source.get("content", "")
                    st.caption(content[:300] + "..." if len(content) > 300 else content)
                    if i < len(sources):
                        st.divider()


def render_single(answer, sources, cached):
    """Render single response (non-comparison mode) with enhanced styling."""
    if cached:
        st.markdown("""
        <span class="status-cached">📦 Cached Response</span>
        """, unsafe_allow_html=True)
    
    st.markdown(answer)
    
    if sources:
        with st.expander("📚 View Sources", expanded=False):
            for i, source in enumerate(sources, 1):
                st.markdown(f"**Source {i}:**")
                content = source.get("content", "")
                st.caption(content[:300] + "..." if len(content) > 300 else content)
                if i < len(sources):
                    st.divider()


if prompt := st.chat_input("Ask a question about your documents...", key="chat_input_compare"):
    current_selected = st.session_state.get("selected_docs", [])
    valid_selected = [t for t in current_selected if t in display_map]
    check_doc_ids = [display_map[t] for t in valid_selected if t in display_map]
    
    if not check_doc_ids:
        st.error("Please select at least one document from the sidebar")
    else:
        # Define doc_ids_to_query early so it's in scope for both compare and single modes
        doc_ids_to_query = check_doc_ids
        
        # Add user message to history (will be rendered below)
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "sources": []
        })
        
        # Enhanced ChatGPT/Claude-style loading animation for Current RAG
        loader_current_rag = """
        <div class="ai-thinking-container">
            <div class="ai-thinking-icon current">📤</div>
            <div style="flex: 1;">
                <div class="ai-dots-container">
                    <div class="ai-thinking-dot current"></div>
                    <div class="ai-thinking-dot current"></div>
                    <div class="ai-thinking-dot current"></div>
                    <div class="ai-thinking-dot current"></div>
                    <div class="ai-thinking-dot current"></div>
                </div>
                <div class="ai-status-text">Retrieving from Current RAG...</div>
                <div class="loading-bar-container">
                    <div class="loading-bar current" style="width: 30%;"></div>
                </div>
            </div>
        </div>
        """
        
        # Enhanced ChatGPT/Claude-style loading animation for LangChain RAG
        loader_langchain = """
        <div class="ai-thinking-container">
            <div class="ai-thinking-icon langchain">🔗</div>
            <div style="flex: 1;">
                <div class="ai-dots-container">
                    <div class="ai-thinking-dot langchain"></div>
                    <div class="ai-thinking-dot langchain"></div>
                    <div class="ai-thinking-dot langchain"></div>
                    <div class="ai-thinking-dot langchain"></div>
                    <div class="ai-thinking-dot langchain"></div>
                </div>
                <div class="ai-status-text">Retrieving from LangChain RAG...</div>
                <div class="loading-bar-container">
                    <div class="loading-bar langchain" style="width: 30%;"></div>
                </div>
            </div>
        </div>
        """
        
        with st.chat_message("assistant"):
            if compare_mode:
                # Side-by-side comparison mode with progress indicators
                st.markdown("""
                <div class="ai-progress-container">
                    <div class="ai-progress-steps">
                        <div class="ai-progress-line">
                            <div class="ai-progress-fill current" style="width: 0%;"></div>
                        </div>
                        <div class="ai-progress-step">
                            <div class="ai-step-indicator current-rag active" id="step1">1</div>
                            <div class="ai-step-label active">Current RAG</div>
                        </div>
                        <div class="ai-progress-step">
                            <div class="ai-step-indicator langchain-rag" id="step2">2</div>
                            <div class="ai-step-label">LangChain RAG</div>
                        </div>
                    </div>
                </div>
                <div style="text-align: center; padding: 12px; background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border-radius: 12px; margin: 8px 0 16px 0;">
                    <span style="font-size: 14px; color: #475569; font-weight: 500;">🔍 Comparing RAG Implementations</span>
                </div>
                """, unsafe_allow_html=True)
                
                # Call current RAG first with themed loading
                thinking_current = st.empty()
                thinking_current.markdown(loader_current_rag, unsafe_allow_html=True)
                
                answer, sources, cached = stream_query_with_placeholder(prompt, check_doc_ids)
                
                thinking_current.empty()
                
                current_result = {
                    "answer": answer,
                    "sources": sources,
                    "cached": cached,
                }
                
                # Update progress indicator to show step 1 completed
                st.markdown("""
                <script>
                    document.getElementById('step1').classList.remove('active');
                    document.getElementById('step1').classList.add('completed');
                    document.getElementById('step1').innerHTML = '✓';
                    document.querySelector('.ai-progress-fill.current').style.width = '50%';
                </script>
                """, unsafe_allow_html=True)
                
                # Then call LangChain with themed loading
                thinking_langchain = st.empty()
                thinking_langchain.markdown(loader_langchain, unsafe_allow_html=True)
                
                answer_lc, sources_lc, cached_lc = stream_query_langchain_with_placeholder(prompt, check_doc_ids)
                
                thinking_langchain.empty()
                
                langchain_result = {
                    "answer": answer_lc,
                    "sources": sources_lc,
                    "cached": cached_lc,
                }
                
# Render side by side
                render_side_by_side(current_result, langchain_result)
                
# This prevents duplicate rendering in the message loop below
            else:
                # Single mode (original behavior) - no comparison
                # doc_ids_to_query is already defined in outer else scope
                
                # Enhanced ChatGPT/Claude-style loading animation for single mode
                loader_single = """
                <div class="ai-thinking-container">
                    <div class="ai-thinking-icon single">🤖</div>
                    <div style="flex: 1;">
                        <div class="ai-dots-container">
                            <div class="ai-thinking-dot single"></div>
                            <div class="ai-thinking-dot single"></div>
                            <div class="ai-thinking-dot single"></div>
                            <div class="ai-thinking-dot single"></div>
                            <div class="ai-thinking-dot single"></div>
                        </div>
                        <div class="ai-status-text">Thinking...</div>
                        <div class="loading-bar-container">
                            <div class="morph-spinner single" style="width: 100%; height: 4px; border-radius: 2px;"></div>
                        </div>
                    </div>
                </div>
                """
                
                thinking_placeholder = st.empty()
                thinking_placeholder.markdown(loader_single, unsafe_allow_html=True)
                
                answer, sources, cached = stream_query_with_placeholder(prompt, doc_ids_to_query)
                
                thinking_placeholder.empty()
                
                render_single(answer, sources, cached)
                
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": sources
                })

for message in st.session_state.messages:
    # Skip rendering if it's a comparison message (already rendered in-place)
    if "comparison" in message:
        continue  # Skip duplicate rendering
    render_message(message["role"], message["content"], message.get("sources"))

if st.button("Clear Chat", type="secondary", key="clear_chat"):
    st.session_state.messages = []
    st.rerun()
