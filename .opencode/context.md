# Codebase Context

This file defines the pre/post-change checklist for all implementer agents.
Use it as a map to the codebase.

## Topic Index

Open `.opencode/context-index.yaml` to find relevant archived OpenSpec specs
by topic. Each entry links to spec files with Requirements + Design decisions.

## Before Any Code Change

1. **Read the topic index** — open `.opencode/context-index.yaml`, find topics relevant to your change area
2. **Read archived specs** — open the linked spec files, read Requirements and Design sections
3. **Read test fixtures** — study conftest files, test doubles, and existing tests for the module
4. **Confirm green baseline** — run `uv run pytest tests/unit/ -q` to verify tests pass before you start

## After Implementing

1. **Lint**: `uv run ruff check .`
2. **Typecheck**: `uv run mypy src/`
3. **Test**: `uv run pytest tests/unit/ -q`
4. **Diff**: `git diff` — review for unintended changes

## Maintenance

When a change is archived, regenerate the topic index:

```bash
uv run python scripts/generate_context_index.py
```
