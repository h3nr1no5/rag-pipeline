"""Inspect what chunks are retrieved for a question on an api-docs document.

Requires a running backend. Authenticates via email/password (creates user
if one doesn't exist).

Usage:
    # Minimal — creates a throwaway user if needed
    uv run python scripts/inspect_api_docs_retrieval.py \\
        --doc-id "<uuid>" \\
        --question "how to add material?"

    # With existing credentials
    uv run python scripts/inspect_api_docs_retrieval.py \\
        --doc-id "<uuid>" \\
        --question "how to add material?" \\
        --email "me@example.com" --password "mypassword123"

    # Adjust retrieval params
    uv run python scripts/inspect_api_docs_retrieval.py \\
        --doc-id "<uuid>" \\
        --question "add cross section" \\
        --top-k 5 --rerank-k 0   # 0 skips cross-encoder, shows raw RRF scores

    # Point at a different server
    uv run python scripts/inspect_api_docs_retrieval.py \\
        --api-url "http://192.168.1.100:8000" \\
        --doc-id "<uuid>" \\
        --question "how to start selection?"
"""

import argparse
import json
import sys
import uuid

import requests


def get_token(api_url: str, email: str | None, password: str | None) -> str:
    """Get an auth token.  Tries login first; if that fails, signs up then logs in.

    Returns the ``access_token`` string.
    """
    if email is None:
        email = f"inspect_{uuid.uuid4().hex[:8]}@example.com"
    if password is None:
        password = "inspectpass123"

    # Try login first
    resp = requests.post(
        f"{api_url}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json()["access_token"]

    # User likely doesn't exist — sign up
    signup = requests.post(
        f"{api_url}/auth/signup",
        json={"email": email, "password": password},
        timeout=10,
    )
    if signup.status_code not in (201, 200):
        print(f"Signup failed ({signup.status_code}): {signup.text}", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(
        f"{api_url}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"Login failed after signup ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()["access_token"]


def query_doc(api_url: str, token: str, doc_id: str, question: str,
              top_k: int, rerank_k: int, max_tokens: int) -> dict:
    """Query the api-docs endpoint and return the parsed JSON response."""
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "query": question,
        "document_id": doc_id,
        "top_k": top_k,
        "rerank_k": rerank_k,
        "max_tokens": max_tokens,
    }
    resp = requests.post(
        f"{api_url}/query/api-docs",
        headers=headers,
        json=body,
        timeout=120,
    )
    if resp.status_code != 200:
        print(f"Query failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def print_results(question: str, data: dict) -> None:
    """Pretty-print the retrieved chunks and response metadata."""
    sep = "─" * 55
    print()
    print(f"╔══ api-docs query ─────────────────────────────────────")
    print(f"║  {question}")
    print(f"╚{'═' * 55}")

    print(f"\n  confidence = {data.get('confidence', 'N/A'):.3f}")
    print(f"  latency    = {data.get('latency_ms', 'N/A')} ms")
    print(f"  cached     = {data.get('cached', False)}")
    print()

    relevant_fns = data.get("relevant_functions", [])
    if relevant_fns:
        print(f"  relevant_functions ({len(relevant_fns)}): {', '.join(relevant_fns)}")

    relevant_types = data.get("relevant_types", [])
    if relevant_types:
        print(f"  relevant_types     ({len(relevant_types)}): {', '.join(relevant_types)}")

    hint = data.get("reasoning_hint", "")
    if hint:
        print(f"\n  reasoning_hint: {hint[:300]}")

    sources = data.get("sources", [])
    if not sources:
        print("\n  No sources returned.")
        return

    for i, s in enumerate(sources, 1):
        chunk_id = s.get("chunk_id", "?")[:8]
        score = s.get("score", 0.0)
        kind = s.get("kind", "")
        iface = s.get("interface_name", "")
        func = s.get("function_name", "")
        type_name = s.get("type_name", "")
        content = s.get("content", "")

        tag = kind if kind else "chunk"
        parts = []
        if iface:
            parts.append(iface)
        if func:
            parts.append(func)
        if type_name and type_name not in parts:
            parts.append(type_name)

        location = ".".join(parts) if parts else ""
        location_str = f"  ({location})" if location else ""

        print()
        print(f"  ── [{i}] score={score:.4f}  kind={tag}  id={chunk_id}{location_str}")
        for line in content.strip().split("\n"):
            print(f"     {line}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect retrieved chunks for an api-docs document",
    )
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1",
                        help="Base API URL (default: http://localhost:8000/api/v1)")
    parser.add_argument("--doc-id", required=True,
                        help="Document ID of the processed api-docs document")
    parser.add_argument("--question", default="how to add material?",
                        help="Query question")
    parser.add_argument("--email",
                        help="Email for auth (auto-generated if omitted)")
    parser.add_argument("--password",
                        help="Password for auth (auto-generated if omitted)")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Number of chunks to retrieve (default: 10)")
    parser.add_argument("--rerank-k", type=int, default=20,
                        help="Candidates to rerank; 0 skips cross-encoder (default: 20)")
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="Max tokens for response generation (default: 2048)")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    token = get_token(api_url, args.email, args.password)

    data = query_doc(
        api_url=api_url,
        token=token,
        doc_id=args.doc_id,
        question=args.question,
        top_k=args.top_k,
        rerank_k=args.rerank_k,
        max_tokens=args.max_tokens,
    )

    print_results(args.question, data)


if __name__ == "__main__":
    main()
