import re
import streamlit as st
import requests
import json

API_BASE_URL = "http://localhost:8000/api/v1"


def _strip_display_text(text: str, include_citations: bool = True) -> str:
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # Strip [Page N] markers unconditionally
    text = re.sub(r'\s*\[Page \d+\]:?\s*', ' ', text)
    # Only strip [Source N] if citations not requested
    if not include_citations:
        text = re.sub(r'\s*\[Source \d+\]', '', text)
    return text


def stream_query(question: str, document_ids: list[str], container=None):
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False, True
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/stream",
            json={"question": question, "document_ids": document_ids},
            headers=headers,
            stream=True,
            timeout=180,
        )
        
        if response.status_code != 200:
            return f"Error: {response.text}", [], False, True
        
        full_response = []
        sources = []
        cached = False
        include_citations = True
        text_container = None
        
        if container:
            text_container = container.empty()
            text_container.markdown("")
        
        for line in response.iter_lines():
            if line:
                line_text = line.decode("utf-8")
                if line_text.startswith("data: "):
                    data_str = line_text[6:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        if "error" in data:
                            return data["error"], [], False, True
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "include_citations" in data:
                            include_citations = data["include_citations"]
                        elif "token" in data:
                            full_response.append(data["token"])
                            if text_container:
                                text_container.markdown(_strip_display_text("".join(full_response), include_citations))
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached, include_citations
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False
    except Exception as e:
        return f"Error: {str(e)}", [], False


def stream_query_with_placeholder(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None):
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False, True
    
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
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/stream",
            json=payload,
            headers=headers,
            stream=True,
            timeout=180,
        )
        
        if response.status_code != 200:
            return f"Error: {response.text}", [], False, True
        
        full_response = []
        sources = []
        cached = False
        include_citations = True
        
        for line in response.iter_lines():
            if line:
                line_text = line.decode("utf-8")
                if line_text.startswith("data: "):
                    data_str = line_text[6:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        if "error" in data:
                            return data["error"], [], False, True
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "include_citations" in data:
                            include_citations = data["include_citations"]
                        elif "token" in data:
                            full_response.append(data["token"])
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached, include_citations
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False, True
    except Exception as e:
        return f"Error: {str(e)}", [], False, True


def stream_query_langchain(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None):
    """Query using LangChain hybrid retrieval (BM25 + FAISS)."""
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False, True
    
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
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/langchain/stream",
            json=payload,
            headers=headers,
            stream=True,
            timeout=180,
        )
        
        if response.status_code != 200:
            return f"Error: {response.text}", [], False, True
        
        full_response = []
        sources = []
        cached = False
        include_citations = True
        
        for line in response.iter_lines():
            if line:
                line_text = line.decode("utf-8")
                if line_text.startswith("data: "):
                    data_str = line_text[6:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        if "error" in data:
                            return data["error"], [], False, True
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "include_citations" in data:
                            include_citations = data["include_citations"]
                        elif "token" in data:
                            full_response.append(data["token"])
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached, include_citations
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False, True
    except Exception as e:
        return f"Error: {str(e)}", [], False, True


def stream_query_langchain_with_placeholder(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None):
    """Query using LangChain with placeholder support."""
    return stream_query_langchain(question, document_ids, temperature, max_tokens, top_k, prompt_sources, response_length)


def query_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None) -> dict:
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
            return {"answer": f"Error: {response.text}", "sources": [], "cached": False}
            
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "sources": [], "cached": False}


def query_langchain_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None) -> dict:
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
            return {"answer": f"Error: {response.text}", "sources": [], "cached": False}
            
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "sources": [], "cached": False}


def stream_query_llamaindex(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None):
    """Query using LlamaIndex-style retrieval."""
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False, True
    
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
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/llamaindex/stream",
            json=payload,
            headers=headers,
            stream=True,
            timeout=180,
        )
        
        if response.status_code != 200:
            return f"Error: {response.text}", [], False, True
        
        full_response = []
        sources = []
        cached = False
        include_citations = True
        
        for line in response.iter_lines():
            if line:
                line_text = line.decode("utf-8")
                if line_text.startswith("data: "):
                    data_str = line_text[6:].strip()
                    
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        if "error" in data:
                            return data["error"], [], False, True
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "include_citations" in data:
                            include_citations = data["include_citations"]
                        elif "token" in data:
                            full_response.append(data["token"])
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached, include_citations
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False, True
    except Exception as e:
        return f"Error: {str(e)}", [], False, True


def stream_query_llamaindex_with_placeholder(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None):
    """Query using LlamaIndex with placeholder support."""
    return stream_query_llamaindex(question, document_ids, temperature, max_tokens, top_k, prompt_sources, response_length)


def query_llamaindex_sync(question: str, document_ids: list[str], temperature: float = None, max_tokens: int = None, top_k: int = None, prompt_sources: int = None, response_length: str = None) -> dict:
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
            return {"answer": f"Error: {response.text}", "sources": [], "cached": False}
            
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "sources": [], "cached": False}
