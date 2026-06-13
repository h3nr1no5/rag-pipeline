

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
