import streamlit as st
import requests
import json

API_BASE_URL = "http://localhost:8000/api/v1"


def stream_query(question: str, document_ids: list[str], container=None):
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False
    
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
            return f"Error: {response.text}", [], False
        
        full_response = []
        sources = []
        cached = False
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
                            return data["error"], [], False
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "token" in data:
                            full_response.append(data["token"])
                            if text_container:
                                text_container.markdown("".join(full_response))
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False
    except Exception as e:
        return f"Error: {str(e)}", [], False


def stream_query_with_placeholder(question: str, document_ids: list[str]):
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False
    
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
            return f"Error: {response.text}", [], False
        
        full_response = []
        sources = []
        cached = False
        
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
                            return data["error"], [], False
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "token" in data:
                            full_response.append(data["token"])
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False
    except Exception as e:
        return f"Error: {str(e)}", [], False


def stream_query_langchain(question: str, document_ids: list[str]):
    """Query using LangChain hybrid retrieval (BM25 + FAISS)."""
    if not st.session_state.get("token"):
        return "Please login to ask questions.", [], False
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/langchain/stream",
            json={"question": question, "document_ids": document_ids},
            headers=headers,
            stream=True,
            timeout=180,
        )
        
        if response.status_code != 200:
            return f"Error: {response.text}", [], False
        
        full_response = []
        sources = []
        cached = False
        
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
                            return data["error"], [], False
                        elif "sources" in data:
                            sources = data["sources"]
                        elif "cached" in data:
                            cached = data["cached"]
                        elif "token" in data:
                            full_response.append(data["token"])
                    except json.JSONDecodeError:
                        continue
        
        return "".join(full_response), sources, cached
        
    except requests.exceptions.Timeout:
        return "Request timed out. Please try again.", [], False
    except Exception as e:
        return f"Error: {str(e)}", [], False


def stream_query_langchain_with_placeholder(question: str, document_ids: list[str]):
    """Query using LangChain with placeholder support."""
    return stream_query_langchain(question, document_ids)


def query_sync(question: str, document_ids: list[str]) -> dict:
    if not st.session_state.get("token"):
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False}
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json={"question": question, "document_ids": document_ids},
            headers=headers,
            timeout=180,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"answer": f"Error: {response.text}", "sources": [], "cached": False}
            
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "sources": [], "cached": False}


def query_langchain_sync(question: str, document_ids: list[str]) -> dict:
    """Sync query using LangChain."""
    if not st.session_state.get("token"):
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False}
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {st.session_state.token}",
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/query/langchain",
            json={"question": question, "document_ids": document_ids},
            headers=headers,
            timeout=180,
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"answer": f"Error: {response.text}", "sources": [], "cached": False}
            
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "sources": [], "cached": False}
