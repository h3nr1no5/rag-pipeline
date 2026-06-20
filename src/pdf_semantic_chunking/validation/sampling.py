import random


class HumanSamplingHelper:
    def sample(self, chunks: list[dict], sample_size: int = 25) -> list[dict]:
        if not chunks:
            return []
        by_type: dict[str, list[dict]] = {}
        for chunk in chunks:
            etype = chunk.get("metadata", {}).get("element_type", "mixed")
            by_type.setdefault(etype, []).append(chunk)

        sampled: list[dict] = []
        per_type = max(1, sample_size // len(by_type))

        for etype, type_chunks in sorted(by_type.items()):
            random.shuffle(type_chunks)
            sampled.extend(type_chunks[:per_type])

        random.shuffle(sampled)
        return sampled[:sample_size]

    def suggest_queries(self, chunks: list[dict]) -> list[str]:
        queries: list[str] = []
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            element_name = meta.get("element_name", "")
            interface = meta.get("interface", "")
            if element_name:
                queries.append(f"How do I use {element_name}?")
                if interface:
                    queries.append(f"What is {interface}.{element_name}?")
        return queries[:10]
