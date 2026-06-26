"""Integration test for the unauthenticated GET /strategies/types endpoint.

Task 9.4 — Verify it returns 200 with the expected schema containing three engine types.

Note: the documents router is mounted at /api/v1 (see src/api/main.py line 461),
so GET /api/v1/strategies/types hits the handler in src/api/routes/documents.py.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app

_PATH = "/api/v1/strategies/types"


@pytest.mark.asyncio
async def test_get_strategy_types_returns_200():
    """GET /strategies/types returns 200 with the expected structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)

    assert response.status_code == 200
    data = response.json()
    assert "types" in data
    assert isinstance(data["types"], dict)


@pytest.mark.asyncio
async def test_strategy_types_contains_three_engines():
    """Response contains recursive, semantic, and api-docs engine types."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)

    types = response.json()["types"]
    assert "recursive" in types
    assert "semantic" in types
    assert "api-docs" in types


@pytest.mark.asyncio
async def test_strategy_types_recursive_has_params():
    """Recursive type has params with expected keys."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)

    recursive = response.json()["types"]["recursive"]
    assert "params" in recursive
    params = recursive["params"]
    assert "chunk_size" in params
    assert "chunk_overlap" in params
    assert "separators" in params
    assert "min_chunk_length" in params
    assert recursive.get("config_schema") is None


@pytest.mark.asyncio
async def test_strategy_types_semantic_has_params():
    """Semantic type has params and the use_hyperlinks field."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)

    semantic = response.json()["types"]["semantic"]
    assert "params" in semantic
    assert "use_hyperlinks" in semantic["params"]
    assert "min_chunk_length" in semantic["params"]


@pytest.mark.asyncio
async def test_strategy_types_api_docs_has_config_schema():
    """API-docs type uses config_schema with all expected parameters."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)

    api_docs = response.json()["types"]["api-docs"]
    assert api_docs.get("params") is None
    assert "config_schema" in api_docs
    schema = api_docs["config_schema"]
    assert "type_patterns" in schema
    assert "heading_policy" in schema
    assert "method_table" in schema
    assert "max_depth" in schema
    assert schema["max_depth"]["type"] == "integer"
    assert schema["max_depth"]["default"] == 3
    assert "format_style" in schema
    assert "include_signatures" in schema
    assert "include_descriptions" in schema
    assert "min_chunk_length" in schema


@pytest.mark.asyncio
async def test_strategy_types_no_auth_required():
    """The endpoint works without authentication headers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(_PATH)
    assert response.status_code == 200
