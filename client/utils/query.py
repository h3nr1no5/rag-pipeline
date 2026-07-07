import logging

import requests

logger = logging.getLogger(__name__)

API_BASE_URL = "http://localhost:8000/api/v1"


def query_sync(question: str, document_ids: list[str], token: str, temperature: float | None = None, max_tokens: int | None = None, top_k: int | None = None, prompt_sources: int | None = None, response_length: str | None = None, include_citations: bool | None = None, clean_response: bool | None = None) -> dict:  # noqa: E501
    if not token:
        return {
            "answer": "Please login to ask questions.",
            "sources": [],
            "cached": False,
            "error": "not_authenticated",
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

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
    if clean_response is not None:
        payload["clean_response"] = clean_response

    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json=payload,
            headers=headers,
            timeout=160,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {
                "answer": "Error: Server encountered an error. Please try again.",
                "sources": [],
                "cached": False,
                "error": "http_error",
            }

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "answer": "Error: Unable to process request. Please try again.",
            "sources": [],
            "cached": False,
            "error": "transport_error",
        }


def query_langchain_sync(question: str, document_ids: list[str], token: str, temperature: float | None = None, max_tokens: int | None = None, top_k: int | None = None, prompt_sources: int | None = None, response_length: str | None = None, include_citations: bool | None = None, clean_response: bool | None = None) -> dict:  # noqa: E501
    """Sync query using LangChain."""
    if not token:
        return {
            "answer": "Please login to ask questions.",
            "sources": [],
            "cached": False,
            "error": "not_authenticated",
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

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
    if clean_response is not None:
        payload["clean_response"] = clean_response

    try:
        response = requests.post(
            f"{API_BASE_URL}/query/langchain",
            json=payload,
            headers=headers,
            timeout=160,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {
                "answer": "Error: Server encountered an error. Please try again.",
                "sources": [],
                "cached": False,
                "error": "http_error",
            }

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "answer": "LangChain query timed out after 180s. Please try again or rephrase your question.",
            "sources": [],
            "cached": False,
            "error": "transport_error",
        }


def query_llamaindex_sync(question: str, document_ids: list[str], token: str, temperature: float | None = None, max_tokens: int | None = None, top_k: int | None = None, prompt_sources: int | None = None, response_length: str | None = None, include_citations: bool | None = None, clean_response: bool | None = None) -> dict:  # noqa: E501
    """Sync query using LlamaIndex."""
    if not token:
        return {
            "answer": "Please login to ask questions.",
            "sources": [],
            "cached": False,
            "error": "not_authenticated",
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
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
    if clean_response is not None:
        payload["clean_response"] = clean_response

    try:
        response = requests.post(
            f"{API_BASE_URL}/query/llamaindex",
            json=payload,
            headers=headers,
            timeout=160,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Backend error {response.status_code}: {response.text[:200]}")
            return {
                "answer": "Error: Server encountered an error. Please try again.",
                "sources": [],
                "cached": False,
                "error": "http_error",
            }

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {"answer": "Error: Unable to process request. Please try again.", "sources": [], "cached": False, "error": "transport_error"}  # noqa: E501


def api_docs_query(api_base_url: str, token: str, query_text: str, document_id: str, top_k: int = 10, verification_enabled: bool = True, max_tokens: int = 2048) -> dict:  # noqa: E501
    """Query API documentation using the API doc pipeline.

    Args:
        api_base_url: Base URL for the API (e.g., "http://localhost:8000/api/v1")
        token: JWT auth token
        query_text: The question to ask
        document_id: The API doc document to search against
        top_k: Number of results to retrieve (default 10)
        verification_enabled: Whether to enable response verification (default True)
        max_tokens: Maximum tokens in generated response (default 2048)

    Returns:
        Parsed JSON response with keys: answer, sources, citations,
        relevant_functions, relevant_types, confidence, cached, latency_ms
    """
    if not token:
        return {"answer": "Please login to ask questions.", "sources": [], "cached": False, "error": "not_authenticated"}  # noqa: E501

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = {
        "query": query_text,
        "document_id": document_id,
        "top_k": top_k,
        "verification_enabled": verification_enabled,
        "max_tokens": max_tokens,
    }

    try:
        response = requests.post(
            f"{api_base_url}/query/api-docs",
            json=payload,
            headers=headers,
            timeout=180,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API docs query error {response.status_code}: {response.text[:200]}")
            return {
                "answer": "Error: Server encountered an error. Please try again.",
                "sources": [],
                "cached": False,
                "error": "http_error",
            }

    except Exception as e:
        logger.error(f"API docs query failed: {e}")
        return {"answer": "Error: Unable to process request. Please try again.", "sources": [], "cached": False, "error": "transport_error"}  # noqa: E501


def async_query_start(
    base_url: str,
    question: str,
    document_ids: list[str],
    token: str,
    params: dict | None = None,
) -> dict:
    """POST /api/v1/query/start and return {task_id, status}.

    Args:
        base_url: API base URL (e.g. "http://localhost:8000/api/v1")
        question: The question to ask
        document_ids: List of document IDs to search
        token: JWT auth token
        params: Optional dict with query parameters.

    Returns:
        Dict with task_id and status on success, or error key on failure.
    """
    if not token:
        return {"error": "not_authenticated"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    p = params or {}
    payload = {
        "question": question,
        "document_ids": document_ids,
        "temperature": p.get("temperature", 0.5),
        "max_tokens": p.get("max_tokens", 600),
        "top_k": p.get("top_k", 5),
        "prompt_sources": p.get("prompt_sources", 3),
        "include_citations": p.get("include_citations", True),
        "response_length": p.get("response_length", "normal"),
        "clean_response": p.get("clean_response", True),
        "link_decay_factor": p.get("link_decay_factor", 0.85),
        "link_expansion_factor": p.get("link_expansion_factor", 2),
        "enable_rag": True,
        "enable_docs": p.get("enable_docs", True),
        "backends": p.get("backends", ["cosine", "langchain", "llamaindex"]),
    }

    try:
        response = requests.post(
            f"{base_url}/query/start",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json()
            logger.info(
                "Query started task_id=%s status=%s", data.get("task_id"), data.get("status"),
            )
            return data
        elif response.status_code == 401:
            return {"error": "unauthorized"}
        else:
            logger.error(
                "Async query start error %s: %s",
                response.status_code,
                response.text[:200],
            )
            return {"error": f"http_error: {response.status_code}"}
    except Exception as e:
        logger.error("Async query start failed: %s", e)
        return {"error": "transport_error"}


def async_query_poll(
    base_url: str,
    task_id: str,
    token: str,
) -> dict:
    """GET /api/v1/query/status/{task_id} and return the task status.

    Args:
        base_url: API base URL (e.g. "http://localhost:8000/api/v1")
        task_id: The task ID to poll
        token: JWT auth token

    Returns:
        Dict with task status, results, progress on success, or error key on failure.
    """
    if not token:
        return {"error": "not_authenticated"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        response = requests.get(
            f"{base_url}/query/status/{task_id}",
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            for r in results:
                answer = r.get("answer", "")
                answer_preview = (
                    (answer[:80] + "...") if len(answer) > 80 else (answer or "(empty)")
                )
                logger.info(
                    "Poll result backend=%s answer_len=%d answer_preview=%s error=%s sources=%d",
                    r.get("backend", "?"), len(answer), answer_preview,
                    r.get("error"), len(r.get("sources", [])),
                )
            logger.info(
                "Poll response status=%s results=%d created_at=%s completed_at=%s",
                data.get("status"), len(results),
                data.get("created_at"), data.get("completed_at"),
            )
            return data
        elif response.status_code == 404:
            return {"error": "task_not_found"}
        elif response.status_code == 401:
            return {"error": "unauthorized"}
        elif response.status_code == 403:
            return {"error": "forbidden"}
        else:
            logger.error(
                "Query poll error %s: %s",
                response.status_code,
                response.text[:200],
            )
            return {"error": f"http_error: {response.status_code}"}
    except requests.ConnectionError:
        logger.error("Query poll connection error")
        return {"error": "connection_error"}
    except requests.Timeout:
        logger.error("Query poll timed out")
        return {"error": "timeout"}
    except Exception as e:
        logger.error("Query poll failed: %s", e)
        return {"error": "transport_error"}
