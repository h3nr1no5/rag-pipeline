from abc import ABC, abstractmethod
from typing import AsyncGenerator


class DocumentParser(ABC):
    @abstractmethod
    async def parse(self, file_path: str) -> str:
        pass

    @abstractmethod
    def get_supported_extensions(self) -> list[str]:
        pass


class PDFParser(DocumentParser):
    def get_supported_extensions(self) -> list[str]:
        return [".pdf"]

    async def parse(self, file_path: str) -> str:
        import asyncio
        
        def _parse():
            import fitz
            doc = fitz.open(file_path)
            text_parts = []
            
            for page_num, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"[Page {page_num + 1}]\n{text}")
            
            doc.close()
            return "\n\n".join(text_parts)
        
        return await asyncio.to_thread(_parse)


class DocxParser(DocumentParser):
    def get_supported_extensions(self) -> list[str]:
        return [".docx"]

    async def parse(self, file_path: str) -> str:
        import asyncio
        
        def _parse():
            from docx import Document
            doc = Document(file_path)
            paragraphs = []
            
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text)
            
            return "\n\n".join(paragraphs)
        
        return await asyncio.to_thread(_parse)


class TextParser(DocumentParser):
    def get_supported_extensions(self) -> list[str]:
        return [".txt", ".md"]

    async def parse(self, file_path: str) -> str:
        import asyncio
        
        def _parse():
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        
        return await asyncio.to_thread(_parse)


class OpenAPIParser:
    def get_supported_extensions(self) -> list[str]:
        return [".yaml", ".yml", ".json"]

    async def parse(self, file_path: str) -> str:
        from .openapi_parser import OpenAPIParser as OpenAPIParserImpl
        parser = OpenAPIParserImpl()
        return await asyncio.to_thread(parser.parse_to_text, file_path)


class ParserRegistry:
    def __init__(self):
        self.parsers: list[DocumentParser] = [
            PDFParser(),
            DocxParser(),
            TextParser(),
            OpenAPIParser(),
        ]

    def get_parser(self, file_path: str) -> DocumentParser | None:
        for parser in self.parsers:
            if any(file_path.lower().endswith(ext) for ext in parser.get_supported_extensions()):
                return parser
        return None

    async def parse(self, file_path: str) -> str:
        parser = self.get_parser(file_path)
        if parser is None:
            raise ValueError(f"No parser found for file: {file_path}")
        return await parser.parse(file_path)
