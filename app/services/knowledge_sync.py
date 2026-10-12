import re #to clean a title and turn it into a filename
from pathlib import Path # much easier and safer for calling file system paths than os.path
from typing import List # used for list containing strings

from app.models import db, KnowledgeItem #SQLAlchemy model
from app.services.vector_store import delete_chunks, upsert_chunks, get_collection #Chroma operations
from app.services.chunker import chunk_markdown #chunking markdown into smaller pieces

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge" #get the knowledge directory path relative to this file (contains the markdown)

def _ensure_knowledge_dir() -> None:
    _KNOWLEDGE_DIR.mkdir(exist_ok=True) #make sure the knowledge directory exists, if not create it

def _slugify(text: str) -> str:
    # Convert a title into a safe Markdown filename.
    text = text.lower()
    text = re.sub(r"[^a-z0-9_\u0600-\u06FF]+", "-", text)
    text = text.strip("-")
    return text or "knowledge"

def _derive_title_and_category(path: Path, content: str):
    # tries to determine the title/category from the markdown file, if not found, it will use the filename as title and "General" as category
    title = path.stem.replace("-", " ").title()
    category = "General"
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            break
    return title, category

def _write_markdown(path: Path, content: str) -> None:
    # Write text to a Markdown file.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")

def _chunk_ids_for_path(path: Path, source: str) -> list:
    # Rechunk a Markdown file only to collect current chunk IDs for deletion.
    content = path.read_text(encoding="utf-8")
    chunks = chunk_markdown(content, source)
    return [chunk["id"] for chunk in chunks]

def _reindex_markdown(path: Path, chunk_ids: List[str] | None = None) -> None:
    # Rechunk one Markdown file and upsert its chunks into Chroma.
    path = path.resolve()
    content = path.read_text(encoding="utf-8")
    source = str(path.relative_to(_KNOWLEDGE_DIR.resolve()))
    chunks = chunk_markdown(content, source)
    if chunk_ids is not None:
        # If specific chunk IDs are given, only reindex those chunks.
        chunk_set = set(chunk_ids)
        chunks = [chunk for chunk in chunks if chunk["id"] in chunk_set]
    upsert_chunks(chunks)

def _purge_orphaned_chroma_chunks(valid_sources) -> None:
    # Delete Chroma chunks whose source is no longer on disk and not mapped in the DB.
    valid_sources = set(valid_sources)
    try:
        collection = get_collection()
        raw = collection.get(include=["metadatas"])
        orphaned_ids = []
        for chunk_id, meta in zip(raw.get("ids", []), raw.get("metadatas", [])):
            source = (meta or {}).get("source", "")
            if source and source not in valid_sources:
                orphaned_ids.append(chunk_id)
        if orphaned_ids:
            delete_chunks(orphaned_ids)
    except Exception:
        pass

def sync_all(force_reindex: bool = False) -> None:
    # Ensure all Markdown files are mirrored into KnowledgeItem records.
    _ensure_knowledge_dir()
    files = sorted(_KNOWLEDGE_DIR.glob("*.md"))
    seen_rel_paths = set()

    for path in files:
        rel = str(path.relative_to(_KNOWLEDGE_DIR))
        seen_rel_paths.add(rel)
        content = path.read_text(encoding="utf-8")
        title, category = _derive_title_and_category(path, content)

        item = KnowledgeItem.query.filter_by(source_path=rel).first()
        if not item:
            db.session.add(KnowledgeItem(title=title, category=category, content=content, source_path=rel))
            db.session.commit()
        elif item.title != title or item.category != category or item.content != content:
            item.title, item.category, item.content = title, category, content
            db.session.commit()

    # Remove DB items whose markdown source was deleted
    orphaned = KnowledgeItem.query.filter(
        KnowledgeItem.source_path != None,
        KnowledgeItem.source_path.notin_(seen_rel_paths),
    ).all()
    for item in orphaned:
        _remove_indexed_chunks_for_item(item)
        db.session.delete(item)
    db.session.commit()

    # Remove Chroma chunks for sources that no longer exist on disk
    # and are no longer represented as KnowledgeItem records.
    try:
        _purge_orphaned_chroma_chunks(seen_rel_paths)
    except Exception:
        pass

    # Reindex markdown files (or all files if force_reindex is True)
    for path in files:
        if force_reindex:
            _reindex_markdown(path)
        else:
            item = KnowledgeItem.query.filter_by(source_path=str(path.relative_to(_KNOWLEDGE_DIR))).first()
            content = path.read_text(encoding="utf-8")
            if item is None or item.content != content:
                _reindex_markdown(path)


def rebuild_vector_index() -> int:
    """Safely reset ChromaDB knowledge collection and rebuild vectors from all Markdown sources.
    Used for model migrations (e.g. migrating to Gemini embeddings) or fresh sync.
    """
    from app.services.vector_store import reset_collection
    reset_collection()
    sync_all(force_reindex=True)
    collection = get_collection()
    return collection.count()


def create_item_from_dashboard(title: str, category: str, content: str) -> KnowledgeItem:
    # Create a new Markdown file from the dashboard and sync it.
    _ensure_knowledge_dir()
    base_slug = _slugify(title)
    rel = f"{base_slug}.md"
    path = _KNOWLEDGE_DIR / rel
    counter = 1
    while path.exists():
        rel = f"{base_slug}-{counter}.md"
        path = _KNOWLEDGE_DIR / rel
        counter += 1

    _write_markdown(path, content or "")
    item = KnowledgeItem(
        title=title,
        category=category or "General",
        content=content or "",
        source_path=rel,
    )
    db.session.add(item)
    db.session.commit()
    _reindex_markdown(path)
    return item


def create_markdown_source_from_admin(filename: str, title: str, category: str, content: str) -> KnowledgeItem:
    """
    Create a Markdown source from the admin UI using an explicit filename.
    Reuses existing file write, DB sync, and Chroma indexing paths.
    """
    _ensure_knowledge_dir()
    raw = (filename or "").strip()
    if not raw:
        raise ValueError("Markdown filename is required.")
    if not raw.lower().endswith(".md"):
        raw = f"{raw}.md"
    # Allow readable Markdown filenames, but prevent directory traversal.
    safe = re.sub(r'[^A-Za-z0-9_.\-]+', '-', raw)
    safe = Path(safe).name
    safe = safe.strip("-") or "knowledge.md"
    if not safe.endswith(".md"):
        safe = f"{safe}.md"

    path = _KNOWLEDGE_DIR / safe
    counter = 1
    base = safe[:-3]
    while path.exists():
        safe = f"{base}-{counter}.md"
        path = _KNOWLEDGE_DIR / safe
        counter += 1

    _write_markdown(path, content or "")
    item = KnowledgeItem(
        title=title or base.replace("-", " ").title(),
        category=category or "General",
        content=content or "",
        source_path=safe,
    )
    db.session.add(item)
    db.session.commit()
    _reindex_markdown(path)
    return item

def update_item_from_dashboard(item: KnowledgeItem, title: str, category: str, content: str) -> None:
    # Update an existing KnowledgeItem and re-sync its Markdown + Chroma vectors.
    if not item.source_path:
        item.source_path = f"{_slugify(title)}.md"
    path = _KNOWLEDGE_DIR / item.source_path
    old_source = item.source_path

    item.title = title
    item.category = category or "General"
    item.content = content or ""
    db.session.commit()

    _remove_indexed_chunks_for_item(item, source=old_source)
    _write_markdown(path, item.content)
    _reindex_markdown(path)

def delete_item_from_dashboard(item: KnowledgeItem) -> None:
    # Delete a KnowledgeItem and remove its chunks from Chroma and disk.
    _remove_indexed_chunks_for_item(item)
    if item.source_path:
        path = _KNOWLEDGE_DIR / item.source_path
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    db.session.delete(item)
    db.session.commit()

def _remove_indexed_chunks_for_item(item: KnowledgeItem, source: str | None = None) -> None:
    if not source:
        source = item.source_path or ""
    if not source:
        return
    path = _KNOWLEDGE_DIR / source
    if path.exists():
        chunk_ids = _chunk_ids_for_path(path, source)
        if chunk_ids:
            delete_chunks(chunk_ids)
    else:
        # Orphaned source removed from disk: delete its chunks by metadata source.
        try:
            collection = get_collection()
            result = collection.get(where={"source": source}, include=["ids"])
            ids = result.get("ids", [])
            if ids:
                delete_chunks(ids)
        except Exception:
            pass
