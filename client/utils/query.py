import re
import streamlit as st
import requests
import json
import logging

logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000/api/v1"


def query_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None, include_citations: bool = None) -> dict:
    if not st.session_state.get("token"):
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False}
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    # Build request payload, excluding None values
    payload = {"question": question, "document_ids": document_ids}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if top_k is not None:
        payload["top_k"] = top_k
    if prompt_sources is not None:
        payload["prompt_sources"] = prompt_sources
    if response_length is not None:
        payload["response_length"] = response_length
    if include_citations is not None:
        payload["include_citations"] = include_citations
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json=payload,
            headers=headers,
            timeout=180,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {"answer": "Error: Service temporarily unavailable.", "sources": [], "cached": False}
            
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"answer": "Error: Unable to process request. Please try again.", "sources": [], "cached": False}


def query_langchain_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None, include_citations: bool = None) -> dict:
    """Sync query using LangChain."""
    if not st.session_state.get("token"):
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False}
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    # Build request payload, excluding None values
    payload = {"question": question, "document_ids": document_ids}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if top_k is not None:
        payload["top_k"] = top_k
    if prompt_sources is not None:
        payload["prompt_sources"] = prompt_sources
    if response_length is not None:
        payload["response_length"] = response_length
    if include_citations is not None:
        payload["include_citations"] = include_citations
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/langchain",
            json=payload,
            headers=headers,
            timeout=180,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {"answer": "Error: Service temporarily unavailable.", "sources": [], "cached": False}
            
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"answer": "Error: Unable to process request. Please try again.", "sources": [], "cached": False}


def query_llamaindex_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None, include_citations: bool = None) -> dict:
    """Sync query using LlamaIndex."""
    if not st.session_state.get("token"):
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False}
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    # Build request payload, excluding None values
    payload = {"question": question, "document_ids": document_ids}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if top_k is not None:
        payload["top_k"] = top_k
    if prompt_sources is not None:
        payload["prompt_sources"] = prompt_sources
    if response_length is not None:
        payload["response_length"] = response_length
    if include_citations is not None:
        payload["include_citations"] = include_citations
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/llamaindex",
            json=payload,
            headers=headers,
            timeout=180,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {"answer": "Error: Service temporarily unavailable.", "sources": [], "cached": False}
            
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"answer": "Error: Unable to process request. Please try again.", "sources": [], "cached": False}
