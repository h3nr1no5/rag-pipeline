from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..extraction.model import DocumentElement

ComElementType = Literal[
    "COM_INTERFACE", "COM_METHOD", "COM_PROPERTY",
    "COM_ENUM", "COM_RECORD", "COM_ERROR_CODE",
]


@dataclass
class ComDocumentElement(DocumentElement):
    com_type: ComElementType | None = None
    element_name: str | None = None
    signature: str | None = None
    return_type: str | None = None
    parameters: list[dict] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    enum_members: list[dict] = field(default_factory=list)
    record_members: list[dict] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    com_confidence: float = 0.0

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "com_type": self.com_type,
            "element_name": self.element_name,
            "signature": self.signature,
            "return_type": self.return_type,
            "parameters": self.parameters,
            "error_codes": self.error_codes,
            "enum_members": self.enum_members,
            "record_members": self.record_members,
            "keywords": self.keywords,
            "com_confidence": self.com_confidence,
        })
        return base
