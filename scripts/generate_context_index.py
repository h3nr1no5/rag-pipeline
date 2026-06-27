#!/usr/bin/env python3
"""Generate .opencode/context-index.yaml from OpenSpec spec files.

Scans all spec files under openspec/changes/, extracts topic names from
directory structure, requirement headings from spec.md, and file references
from design.md. Outputs a YAML index agents can use as a table of contents
to find relevant archived specs before making code changes.

Usage: uv run python scripts/generate_context_index.py
"""

import re
from pathlib import Path
from collections import defaultdict

import yaml


CHANGES_DIR = Path("openspec/changes").resolve()
OUTPUT_PATH = Path(".opencode/context-index.yaml").resolve()


def extract_topic(spec_path: Path) -> str:
    parts = spec_path.relative_to(CHANGES_DIR).parts
    for i, p in enumerate(parts):
        if p == "specs" and i + 1 < len(parts):
            return parts[i + 1].replace("-", "_")
    return "misc"


def extract_requirements(spec_path: Path) -> list[str]:
    content = spec_path.read_text()
    return re.findall(
        r"### Requirement:\s*(.+?)(?:\s*\((?:UPDATED|REMOVED)\))?\s*$",
        content,
        re.MULTILINE,
    )


def extract_file_refs(change_dir: Path) -> list[str]:
    refs: set[str] = set()
    for md_file in change_dir.rglob("*.md"):
        content = md_file.read_text()
        refs.update(re.findall(r"`([\w./-]+\.py)`", content))
        refs.update(re.findall(r"`([\w./-]+\.sqlite)`", content))
        refs.update(re.findall(r"`([\w./-]+\.yaml)`", content))
    return sorted(refs)


def main() -> None:
    spec_files = list(CHANGES_DIR.rglob("specs/*/spec.md"))
    if not spec_files:
        print("No spec files found under openspec/changes/")
        return

    topics: dict[str, dict] = defaultdict(
        lambda: {"specs": [], "requirements": [], "key_files": set()}
    )

    root = Path.cwd().resolve()
    for spec_path in sorted(spec_files):
        topic = extract_topic(spec_path)
        rel = spec_path.relative_to(root).as_posix()
        requirements = extract_requirements(spec_path)
        change_dir = spec_path.parent.parent.parent
        file_refs = extract_file_refs(change_dir)

        topics[topic]["specs"].append(rel)
        topics[topic]["requirements"].extend(requirements)
        topics[topic]["key_files"].update(file_refs)

    index: dict[str, dict] = {}
    for name, data in sorted(topics.items()):
        reqs = list(dict.fromkeys(data["requirements"]))
        summary = reqs[0] if reqs else name.replace("_", "-")

        entry: dict = {"summary": summary, "specs": data["specs"]}
        if data["key_files"]:
            entry["key_files"] = sorted(data["key_files"])
        index[name] = entry

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        yaml.dump(
            {"topics": index},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    )
    print(f"Wrote {OUTPUT_PATH} ({len(index)} topics)")


if __name__ == "__main__":
    main()
