This change has no new or modified capabilities — it is a code hygiene change.

- **No new capabilities**: No new spec is required.
- **No modified capabilities**: No existing spec requirements change.

Implementation is purely in test helper function signatures (type narrowing) and removal of stale `# type: ignore[arg-type]` annotations. See `proposal.md` and `design.md` for details.
