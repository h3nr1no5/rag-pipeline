"""Dataset loader for RAG evaluation."""
import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvalQuestion:
    id: str
    question: str
    document: str
    expected_sources: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    min_answer_length: int = 0


@dataclass
class EvalDocument:
    filename: str
    path: str


@dataclass
class EvalDataset:
    version: str
    created: str
    description: str
    documents: list[EvalDocument] = field(default_factory=list)
    questions: list[EvalQuestion] = field(default_factory=list)


def load_dataset(path: str) -> EvalDataset:
    """Load and validate an evaluation dataset from a JSON file.

    Validation checks:
    - File must exist (raises FileNotFoundError)
    - Version field must be present
    - At least one question must be defined
    - Each referenced document file must exist (raises FileNotFoundError)
    - Warns if an expected_source doesn't match in its document (non-fatal)

    Args:
        path: Path to the eval_dataset.json file

    Returns:
        EvalDataset object with validated data

    Raises:
        FileNotFoundError: If the dataset file or a referenced document doesn't exist
        ValueError: If the dataset JSON is malformed
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    if "version" not in data:
        raise ValueError("Dataset must have a 'version' field")

    documents = []
    for doc_data in data.get("documents", []):
        doc_path = doc_data["path"]
        if not os.path.exists(doc_path):
            raise FileNotFoundError(f"Referenced document not found: {doc_path}")
        documents.append(
            EvalDocument(
                filename=doc_data["filename"],
                path=doc_data["path"],
            )
        )

    questions = []
    for q_data in data.get("questions", []):
        q = EvalQuestion(
            id=q_data["id"],
            question=q_data["question"],
            document=q_data["document"],
            expected_sources=q_data.get("expected_sources", []),
            expected_keywords=q_data.get("expected_keywords", []),
            min_answer_length=q_data.get("min_answer_length", 0),
        )
        questions.append(q)

    if not questions:
        raise ValueError("Dataset must have at least one question")

    # Warn if expected_sources don't appear in their document (non-fatal validation)
    for q in questions:
        doc = next((d for d in documents if d.filename == q.document), None)
        if doc and q.expected_sources:
            try:
                with open(doc.path) as f:
                    content = f.read()
                for source in q.expected_sources:
                    if source not in content:
                        logger.warning(
                            f"Question {q.id}: expected_source text not found in {doc.filename}: "
                            f"{source[:80]!r}..."
                        )
            except Exception as e:
                logger.warning(f"Question {q.id}: Could not validate expected_sources: {e}")

    return EvalDataset(
        version=data["version"],
        created=data.get("created", ""),
        description=data.get("description", ""),
        documents=documents,
        questions=questions,
    )
