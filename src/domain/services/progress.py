def compute_stage_progress(
    processing_step: str | None,
    saved_chunks: int,
    chunk_count: int,
) -> dict[str, int]:
    """
    Returns {"parsing": 0..100, "chunking": 0..100, "saving": 0..100}

    Logic:
    - parsing: 100 if step is past parsing (chunking/saving/completed), else 0
    - chunking: 100 if step is past chunking (saving/completed), else 0
    - saving: computed from saved_chunks/chunk_count if step is "saving",
              100 if completed, 0 otherwise
    """
    p = {"parsing": 0, "chunking": 0, "saving": 0}

    if processing_step in ("chunking", "saving", "completed"):
        p["parsing"] = 100
    if processing_step in ("saving", "completed"):
        p["chunking"] = 100
    if processing_step == "saving" and chunk_count > 0:
        p["saving"] = min(100, int(100 * saved_chunks / chunk_count))
    elif processing_step == "completed":
        p["saving"] = 100

    return p
