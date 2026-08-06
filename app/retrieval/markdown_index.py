"""Stable Markdown manual parser shared by retrieval implementations."""
from __future__ import annotations

import hashlib
import pathlib
import re

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
META_RE = re.compile(r"^(Document ID|Revision|Language|Classification):\s*(.+?)\s*$")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def parse_manual(path: pathlib.Path, root: pathlib.Path) -> tuple[dict, list[dict]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("manual requires one H1 title")
    metadata = {}
    for line in lines[1:]:
        match = META_RE.match(line)
        if match:
            metadata[match[1]] = match[2]
        if HEADING_RE.match(line):
            break
    if set(metadata) != {"Document ID", "Revision", "Language", "Classification"}:
        raise ValueError("manual metadata is incomplete")
    sections, heading, body = [], None, []

    def append_section() -> None:
        if heading is None:
            return
        section_text = "\n".join(body).strip()
        if not section_text:
            raise ValueError(f"empty section: {heading}")
        chunk_id = f"{metadata['Document ID']}#{_slugify(heading)}"
        sections.append({"chunk_id": chunk_id, "document_id": metadata["Document ID"], "heading": heading,
                         "ordinal": len(sections) + 1, "text": section_text,
                         "text_sha256": hashlib.sha256(section_text.encode("utf-8")).hexdigest(),
                         "citation": {"document_id": metadata["Document ID"], "chunk_id": chunk_id,
                                      "source": path.name, "section": heading}})

    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            append_section()
            heading, body = match[1], []
        elif heading is not None:
            body.append(line)
    append_section()
    document = {"document_id": metadata["Document ID"], "revision": metadata["Revision"],
                "source_path": path.relative_to(root).as_posix(),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "title": lines[0][2:].strip(), "language": metadata["Language"],
                "classification": metadata["Classification"]}
    return document, sections
