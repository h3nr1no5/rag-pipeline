

def build_augmented_text(chunk_content: str, chunk_metadata: dict) -> str:
    element_type = chunk_metadata.get("element_type")
    interface = chunk_metadata.get("interface")
    element_name = chunk_metadata.get("element_name")
    section = chunk_metadata.get("section")

    if element_type in ("function", "property", "enum", "record", "error_code") and interface and element_name:
        type_title = element_type.replace("_", " ").title()
        prefix = f"COM API {type_title}: {interface}.{element_name}"
        parts = [
            prefix,
            f"Interface: {interface}",
            f"Section: {section or ''}",
            f"Element Type: {element_type}",
            f"Element Name: {element_name}",
            "",
            chunk_content,
        ]
        return "\n".join(parts)

    section_hierarchy = chunk_metadata.get("section_hierarchy", [])
    if section_hierarchy:
        prefix = f"[Section: {' > '.join(section_hierarchy)}]"
        return f"{prefix}\n{chunk_content}"

    if element_type:
        return f"[{element_type}]\n{chunk_content}"

    return chunk_content


def build_augmented_text_with_links(
    chunk_content: str,
    chunk_metadata: dict,
    link_target_contents: dict[str, str] | None = None,
) -> str:
    """Build augmented text that includes link context from chunk metadata.

    Calls ``build_augmented_text`` for the base prefix, then appends
    ``Links To:`` and ``Referenced From:`` blocks when the metadata
    contains ``links`` or ``backlinks`` arrays.

    Parameters
    ----------
    chunk_content:
        The plain text content of the chunk.
    chunk_metadata:
        Metadata dict that may contain ``links`` and/or ``backlinks`` arrays.
    link_target_contents:
        Optional mapping from chunk ID to content text, used to resolve
        link and backlink targets for summarisation.

    Returns
    -------
    Augmented text string suitable for embedding computation. The original
    chunk content in the database is never modified.
    """
    base_text = build_augmented_text(chunk_content, chunk_metadata)

    links = chunk_metadata.get("links") or []
    backlinks = chunk_metadata.get("backlinks") or []

    if not links and not backlinks:
        return base_text

    contents = link_target_contents or {}
    parts = [base_text]

    # --- Outgoing links ---------------------------------------------------
    if links:
        link_lines: list[str] = ["", "Links To:"]
        seen_targets: set[tuple[str, ...]] = set()
        link_count = 0

        for link in links:
            if link_count >= 3:
                break

            target_ids = link.get("target_chunk_ids") or []
            # Deduplicate by sorted tuple of target IDs, fall back to URI
            dedup_key = (
                tuple(sorted(target_ids)) if target_ids else (link.get("uri") or "",)
            )
            if dedup_key in seen_targets:
                continue
            seen_targets.add(dedup_key)

            if target_ids:
                # Internal link — try to resolve content for the first
                # target whose content we have.
                resolved = False
                for tid in target_ids:
                    target_text = contents.get(tid)
                    if target_text:
                        link_lines.append(
                            f"- {target_text[:150]} (type: internal)"
                        )
                        link_count += 1
                        resolved = True
                        break
                if resolved:
                    continue
                # All target IDs present but none resolved → skip link
                # (no fallback specified in requirements)
            else:
                # External or unresolved link — show the URI
                uri = link.get("uri") or "unknown"
                link_lines.append(f"- {uri} (type: external)")
                link_count += 1

        if len(link_lines) > 1:  # at least one entry was added
            parts.append("\n".join(link_lines))

    # --- Backlinks --------------------------------------------------------
    if backlinks:
        bl_lines: list[str] = ["", "Referenced From:"]
        seen_sources: set[str] = set()
        bl_count = 0

        for bl in backlinks:
            if bl_count >= 3:
                break

            source_id = bl.get("source_chunk_id") or ""
            if not source_id or source_id in seen_sources:
                continue
            seen_sources.add(source_id)

            source_text = contents.get(source_id)
            if source_text is not None:
                bl_lines.append(f"- {source_text[:150]} (type: internal)")
            else:
                bl_lines.append("- [deleted chunk]")
            bl_count += 1

        if len(bl_lines) > 1:  # at least one entry was added
            parts.append("\n".join(bl_lines))

    result = "\n".join(parts)

    # If nothing was appended (all links/backlinks filtered out), return
    # the base text as-is.
    return result if result != base_text else base_text
