import logging
from collections import Counter

logger = logging.getLogger(__name__)


class RequiredFieldValidator:
    def validate(self, chunks: list[dict]) -> dict:
        warnings: list[str] = []
        total = len(chunks)
        passed = 0

        for i, chunk in enumerate(chunks):
            meta = chunk.get("metadata", {})
            element_type = meta.get("element_type")
            has_errors = False

            if element_type in ("function", "property", "enum", "record", "error_code"):
                if not meta.get("interface"):
                    warnings.append(f"missing_field: interface on chunk_{i}")
                    has_errors = True
                if not meta.get("element_name"):
                    warnings.append(f"missing_field: element_name on chunk_{i}")
                    has_errors = True

            if element_type == "function":
                content = chunk.get("content", "")
                if "return" not in content.lower():
                    warnings.append(f"missing_return: chunk_{i} function lacks 'return' keyword")
                    has_errors = True

            if not has_errors:
                passed += 1

        return {
            "total_chunks": total,
            "passed": passed,
            "warnings": len(warnings),
            "warnings_detail": warnings,
        }


class TokenDistributionAnalyzer:
    def analyze(self, chunks: list[dict]) -> dict:
        token_counts = [c.get("metadata", {}).get("token_count", 0) for c in chunks]

        if not token_counts:
            return {"min": 0, "max": 0, "mean": 0, "p50": 0, "p90": 0, "p95": 0, "total": 0}

        sorted_counts = sorted(token_counts)
        n = len(sorted_counts)

        return {
            "min": sorted_counts[0],
            "max": sorted_counts[-1],
            "mean": sum(token_counts) / n,
            "p50": sorted_counts[n * 50 // 100],
            "p90": sorted_counts[n * 90 // 100],
            "p95": sorted_counts[n * 95 // 100],
            "total": sum(token_counts),
        }


class ValidationReportBuilder:
    def build(self, chunks: list[dict]) -> dict:
        validator = RequiredFieldValidator()
        analyzer = TokenDistributionAnalyzer()

        validation = validator.validate(chunks)
        distribution = analyzer.analyze(chunks)
        validation["token_distribution"] = distribution

        type_counts = Counter(
            c.get("metadata", {}).get("element_type", "mixed") for c in chunks
        )
        validation["element_type_counts"] = dict(type_counts)

        return validation
