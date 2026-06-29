from dataclasses import dataclass, field


@dataclass
class ChunkNode:
    chunk_id: str
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    kind: str = "section"  # interface, method, property, parameter, enum, enum_value, error_code
    level: int = 0  # 0=interface, 1=method/property/enum, 2=parameter
    source_doc: str = ""
    content: str = ""
    metadata: dict = field(default_factory=dict)  # enriched with interface_name, function_name etc.
