"""Test doubles module for the RAG pipeline project.

This module provides lightweight, deterministic replacements for
heavy external dependencies (embedding models, LLMs, etc.) so that
tests can run quickly without loading real models or making network
calls.

Each test double implements the corresponding protocol/ABC from
``src.domain.ports`` with simplified, deterministic logic suitable
for unit and integration testing.
"""
