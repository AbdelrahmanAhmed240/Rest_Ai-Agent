import re
from pathlib import Path
from typing import List, Dict

# Cleans text into a safe, stable ID format.
def _clean_id(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^a-z0-9_\-\.]+", "-", text.lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "entity"

# Extracts values from a key:value line in Markdown text.
def _extract_frontmatter_value(text: str, key: str) -> str | None:
    pattern = rf"^{key}:\s*(.+)"
    for line in text.splitlines():
        match = re.match(pattern, line.strip(), flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value
    return None

# Splits Markdown text into blocks based on headings.
def _split_items(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n")
    parts = re.split(r"\n## ", normalized)
    if not parts:
        return [text.strip()]
    first = parts[0].strip()
    items: List[str] = []
    if first:
        items.append(first)
    for part in parts[1:]:
        items.append("## " + part)
    return items

# Converts a Markdown file into structured chunks with stable IDs and metadata.
def chunk_markdown(text: str, source: str) -> List[Dict]:
    # Convert one Markdown source into stable semantic chunks.
    if not text or not text.strip():
        return []

    blocks = _split_items(text)
    chunks: List[Dict] = []

    for block in blocks:
        lines = block.splitlines()
        title_line = None
        for line in lines:
            # Use the first heading as the chunk title.
            if line.startswith("#"):
                title_line = line.lstrip("#").strip()
                break
        if not title_line:
            continue

        # Read metadata from frontmatter-style lines inside the block.
        type_ = _extract_frontmatter_value(block, "type") or "section"
        name_ = _extract_frontmatter_value(block, "name") or title_line
        category_ = _extract_frontmatter_value(block, "category") or ""
        entity_id = _extract_frontmatter_value(block, "id")
        if not entity_id:
            # Stable fallback ID from title so edits do not break lookups.
            entity_id = _clean_id(title_line)

        # Build a globally unique chunk ID based on source file + entity.
        chunk_id = f"{Path(source).stem}-{entity_id}"

        chunks.append(
            {
                "id": chunk_id,
                "source": source,
                "type": type_,
                "name": name_,
                "category": category_,
                "text": block.strip(),
            }
        )
    return chunks
