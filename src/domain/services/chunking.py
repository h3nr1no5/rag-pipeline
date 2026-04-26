from typing import Optional
from ..entities import ChunkingStrategy


class RecursiveChunkingService:
    def __init__(self, strategy: ChunkingStrategy):
        self.strategy = strategy

    def chunk_text(self, text: str) -> list[dict]:
        chunks = []
        separators = self.strategy.separators
        chunk_size = self.strategy.chunk_size
        chunk_overlap = self.strategy.chunk_overlap

        def split_text(text: str, separator_index: int = 0) -> list[str]:
            if separator_index >= len(separators):
                return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            
            separator = separators[separator_index]
            parts = text.split(separator)
            
            result = []
            current = ""
            
            for part in parts:
                if len(current) + len(separator) + len(part) <= chunk_size:
                    current += part + separator if current else part
                else:
                    if current:
                        result.append(current.strip())
                    current = part
            
                while len(current) > chunk_size:
                    result.append(current[:chunk_size])
                    current = current[chunk_size - chunk_overlap:]
            
            if current:
                result.append(current.strip())
            
            return result

        raw_chunks = split_text(text)
        
        for i, chunk_content in enumerate(raw_chunks):
            if len(chunk_content.strip()) < 20:
                continue
            
            chunks.append({
                "content": chunk_content.strip(),
                "chunk_index": i,
                "metadata": {
                    "chunking_strategy_id": self.strategy.id,
                    "char_count": len(chunk_content),
                }
            })
        
        return chunks

    def chunk_text_by_tokens(self, text: str) -> list[dict]:
        import re
        tokens = re.findall(r'\S+|\n', text)
        chunks = []
        chunk_size = self.strategy.chunk_size
        chunk_overlap = self.strategy.chunk_overlap
        
        i = 0
        chunk_index = 0
        
        while i < len(tokens):
            chunk_tokens = tokens[i:i + chunk_size]
            chunk_content = " ".join(chunk_tokens)
            
            if len(chunk_content.strip()) >= 20:
                chunks.append({
                    "content": chunk_content.strip(),
                    "chunk_index": chunk_index,
                    "metadata": {
                        "chunking_strategy_id": self.strategy.id,
                        "token_count": len(chunk_tokens),
                    }
                })
                chunk_index += 1
            
            i += chunk_size - chunk_overlap
        
        return chunks


def create_chunking_service(strategy: ChunkingStrategy) -> RecursiveChunkingService:
    return RecursiveChunkingService(strategy)
