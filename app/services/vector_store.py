import os
from typing import Dict, List

from config import config
from app.services.embeddings import embed_query, embed_texts

_client = None
_collection = None
_IMPORT_ERROR = None

def _import_chromadb():
    global _IMPORT_ERROR
    try:
        # Lazy import so the app can still start if Chroma is missing.
        import chromadb
        from chromadb.config import Settings
        return chromadb, Settings
    except Exception as exc:
        _IMPORT_ERROR = exc
        return None, None

def _ensure_chroma():
    # Fail fast on vector operations if Chroma could not be imported.
    if _IMPORT_ERROR is not None:
        raise RuntimeError(f"chromadb is required. Original error: {_IMPORT_ERROR}")

def get_client():
    global _client
    _ensure_chroma()
    if _client is None:
        chromadb, Settings = _import_chromadb()
        path = config.CHROMA_PERSIST_DIR
        os.makedirs(path, exist_ok=True)
        # Persistent local Chroma client stored on disk.
        _client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False),
        )
    return _client

def get_collection():
    # Return the single shared knowledge collection.
    chromadb, _ = _import_chromadb()
    client = get_client()
    return client.get_or_create_collection(name="knowledge")

def _metadata(chunk: Dict) -> Dict:
    # Store only the metadata needed for filtering and display.
    return {
        "source": chunk.get("source", ""),
        "type": chunk.get("type", ""),
        "name": chunk.get("name", ""),
        "category": chunk.get("category", ""),
    }

def add_chunks(chunks: List[Dict]) -> None:
    # Add new chunks to Chroma with embeddings and metadata.
    if not chunks:
        return
    _ensure_chroma()
    collection = get_collection()
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(documents)
    metadatas = [_metadata(chunk) for chunk in chunks]
    collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

def _upsert_chunk_embeddings(chunks: List[Dict]) -> None:
    # Replace existing vectors for the same chunk IDs.
    if not chunks:
        return
    _ensure_chroma()
    collection = get_collection()
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    embeddings = embed_texts(documents)
    metadatas = [_metadata(chunk) for chunk in chunks]
    collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

def upsert_chunks(chunks: List[Dict]) -> None:
    # Public upsert entry point used by sync/reindex flows.
    _upsert_chunk_embeddings(chunks)

def delete_chunks(ids: List[str]) -> None:
    # Remove vectors by chunk ID when Markdown sources change or are deleted.
    if not ids:
        return
    _ensure_chroma()
    collection = get_collection()
    collection.delete(ids=ids)

def retrieve(query: str, top_k: int = 5) -> List[Dict]:
    # Semantic search: embed the query, then return the closest Chroma hits.
    if not query.strip():
        return []
    _ensure_chroma()
    collection = get_collection()
    query_embedding = embed_query(query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    hits: List[Dict] = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for idx, doc in enumerate(documents):
        hits.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "content": doc,
                "metadata": metadatas[idx] if idx < len(metadatas) else {},
                "score": distances[idx] if idx < len(distances) else None,
            }
        )
    return hits