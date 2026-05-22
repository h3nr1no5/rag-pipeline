import streamlit as st
import requests
import time

from client.components.auth_guard import auth_guard
from client.utils.api_client import logout
from client.components.chat_message import strip_markdown_formatting

st.set_page_config(page_title="Query History - RAG Pipeline", page_icon="📜")

API_BASE_URL = "http://localhost:8000/api/v1"

auth_guard()

st.title("📜 Query History")

headers = {"Authorization": f"Bearer {st.session_state.token}"}

try:
    models_response = requests.get(f"{API_BASE_URL}/health/models", timeout=30)
    if models_response.status_code == 200:
        models_data = models_response.json()
        all_ready = models_data.get("all_ready", False)
        
        if all_ready:
            st.success("✅ AI models ready")
        else:
            llm_info = models_data.get("llm", {})
            embedder_info = models_data.get("embedder", {})
            
            llm_status = llm_info.get("status", "")
            embedder_status = embedder_info.get("status", "")
            
            loading = llm_status in ("downloading", "not_started") or embedder_status in ("downloading", "not_loaded")
            if loading:
                st.warning("⏳ AI models are still loading...")
except:
    pass

from datetime import datetime

try:
    response = requests.get(f"{API_BASE_URL}/query/history", headers=headers)
    if response.status_code == 200:
        data = response.json()
        queries = data.get("queries", [])
        
        if not queries:
            st.info("No query history yet. Start chatting in the Chat page!")
        else:
            st.markdown(f"**Total queries:** {len(queries)}")
            st.divider()
            
            for query in queries:
                with st.expander(f"**Q:** {query['query_text'][:100]}{'...' if len(query['query_text']) > 100 else ''}"):
                    st.markdown("**Question:**")
                    st.markdown(query["query_text"])
                    
                    st.markdown("**Answer:**")
                    st.markdown(strip_markdown_formatting(query["response_text"]))
                    
                    if query.get("source_chunk_ids"):
                        st.markdown(f"**Sources used:** {len(query['source_chunk_ids'])} chunks")
                    
                    created = query.get("created_at", "")
                    expires = query.get("expires_at", "")
                    
                    st.caption(f"Asked: {created[:19].replace('T', ' ')} | Expires: {expires[:19].replace('T', ' ')}")
    else:
        st.error("Failed to load query history")
except Exception as e:
    st.error(f"Error: {str(e)}")

st.sidebar.divider()

if st.sidebar.button("Clear Cache", use_container_width=True):
    try:
        clear_response = requests.delete(f"{API_BASE_URL}/query/clear", headers=headers)
        if clear_response.status_code == 204:
            st.sidebar.success("Cache cleared!")
            time.sleep(1)
            st.rerun()
        else:
            st.sidebar.error("Failed to clear cache")
    except Exception as e:
        st.sidebar.error(f"Error: {str(e)}")

if st.sidebar.button("Logout", use_container_width=True):
    logout()
    st.rerun()
