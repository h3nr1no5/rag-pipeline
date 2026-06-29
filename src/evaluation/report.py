"""Report generation for RAG evaluation results."""
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _timestamp_str() -> str:
    """Get an ISO-like timestamp string safe for filenames."""
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def write_json_report(report: dict, output_dir: str) -> str:
    """Write evaluation report as JSON.

    Args:
        report: Report dictionary with results and summary
        output_dir: Directory to write the report to

    Returns:
        Path to the written JSON file
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"report_{_timestamp_str()}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"JSON report written to {filepath}")
    return filepath


def write_markdown_report(report: dict, output_dir: str) -> str:
    """Write evaluation report as Markdown with tables.

    Args:
        report: Report dictionary with results and summary
        output_dir: Directory to write the report to

    Returns:
        Path to the written Markdown file
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"report_{_timestamp_str()}.md"
    filepath = os.path.join(output_dir, filename)

    lines = []
    lines.append("# RAG Evaluation Report\n")
    lines.append(f"- **Timestamp**: {report.get('timestamp', 'N/A')}")
    lines.append(f"- **Dataset Version**: {report.get('dataset_version', 'N/A')}")
    lines.append(f"- **Backends**: {', '.join(report.get('backends', []))}")
    cfg = report.get("config", {})
    top_k = cfg.get("top_k", "N/A")
    temp = cfg.get("temperature", "N/A")
    lines.append(f"- **Config**: top_k={top_k}, temperature={temp}")
    lines.append("")

    # Summary section
    summary = report.get("summary", {})
    if summary:
        lines.append("## Per-Backend Summary\n")
        # Build dynamic column headers from first backend's keys
        backends = list(summary.keys())
        if backends:
            metrics = list(summary[backends[0]].keys())
            header = "| Metric | " + " | ".join(b for b in backends) + " |"
            separator = "|" + "---|" * (len(backends) + 1)
            lines.append(header)
            lines.append(separator)
            for metric in metrics:
                row = f"| {metric} |"
                for backend in backends:
                    val = summary[backend].get(metric, "N/A")
                    if isinstance(val, float):
                        row += f" {val:.4f} |"
                    else:
                        row += f" {val} |"
                lines.append(row)
            lines.append("")

    # Per-question results
    results = report.get("results", {})
    if results:
        lines.append("## Per-Question Results\n")
        for qid, backends_data in sorted(results.items()):
            lines.append(f"### {qid}\n")
            for backend, metrics in backends_data.items():
                lines.append(f"**{backend}**  ")
                for metric, val in metrics.items():
                    if isinstance(val, float):
                        lines.append(f"- {metric}: {val:.4f}")
                    else:
                        lines.append(f"- {metric}: {val}")
                lines.append("")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    logger.info(f"Markdown report written to {filepath}")
    return filepath
