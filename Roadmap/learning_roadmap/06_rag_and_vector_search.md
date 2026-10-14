# Module 06 — RAG and Vector Search

## 1. What is RAG and Why Does This Project Need It?
**RAG** stands for **Retrieval-Augmented Generation**.

Without RAG, if a customer asks:
*"What are your opening hours for the Gleem branch?"* or *"Do you have student discounts?"*
The LLM might guess or give a generic answer because it was never trained on this specific restaurant's internal operating manual.

With RAG:
1. We retrieve the exact paragraph from the restaurant's Markdown files (`knowledge/details.md`).
2. We inject that paragraph into the LLM's prompt context.
3. The LLM synthesizes an accurate answer grounded entirely in factual ground truth.

---

## 2. Knowledge Document Architecture
Look inside the `knowledge/` folder:
- [`knowledge/menu.md`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/knowledge/menu.md): Structured Markdown containing dishes, ingredients, prices, and combos.
- [`knowledge/details.md`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/knowledge/details.md): Operating policies, branch locations, working hours, hotline numbers, and discount rules.

---

## 3. The 4-Step RAG Pipeline

```
[Markdown Docs]  --> 1. Chunking (chunker.py)
                 --> 2. Embeddings (embeddings.py)
                 --> 3. ChromaDB Indexing (vector_store.py)
                                  |
[User Query]     --> 4. Semantic Search (vector_store.py::retrieve) --> Injected Context
```

### Step 1: Semantic Chunking (`app/services/chunker.py`)
Open [`app/services/chunker.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/chunker.py#L38-L80).
- If you embed an entire 50-page document as one chunk, search accuracy degrades.
- `chunk_markdown(text, source)` splits the document along `## ` section headings.
- For each section, it extracts frontmatter metadata (`type`, `name`, `category`, `id`) and generates a stable unique chunk ID (e.g. `details-branches`, `menu-break-meal`).

### Step 2: Vector Embeddings (`app/services/embeddings.py`)
Open [`app/services/embeddings.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/embeddings.py#L27-L68).
- **What is an embedding?** A list of floating-point numbers (e.g., 768 dimensions) representing the semantic meaning of text in multi-dimensional vector space. Words with similar meanings have high cosine similarity.
- The project calls Google's official `gemini-embedding-001` model via `client.models.embed_content()`.
- `embed_texts(texts)` batches chunks up to 50 at a time.
- `embed_query(query)` embeds the single incoming user question.

### Step 3: ChromaDB Vector Store (`app/services/vector_store.py`)
Open [`app/services/vector_store.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/vector_store.py#L27-L123).
- **ChromaDB**: An open-source, embedded vector database stored locally on disk at `data/chroma_db/`.
- `upsert_chunks(chunks)`: Prepares the IDs, text contents, embeddings, and metadata dictionaries, and stores them in the persistent `knowledge` collection.
- `retrieve(query, top_k=5)`:
  1. Embeds the user query via `embed_query(query)`.
  2. Executes vector cosine similarity search in Chroma.
  3. Returns the top `k` most relevant chunks with their content, metadata, and distance scores.

### Step 4: Knowledge Synchronization (`app/services/knowledge_sync.py`)
Open [`app/services/knowledge_sync.py`](file:///c:/Users/Home/Desktop/Rest_Ai-Agent/app/services/knowledge_sync.py#L70-L135).
- If an admin edits a markdown file or adds new policies via the web UI, `sync_all()`:
  1. Compares disk files against the `KnowledgeItem` SQLite table.
  2. Updates changed database rows.
  3. Deletes orphaned chunks from ChromaDB whose markdown files were deleted (`_purge_orphaned_chroma_chunks`).
  4. Upserts fresh embeddings into ChromaDB (`_reindex_markdown`).

---
👉 **Next**: Continue to [**Module 07: LangGraph and AI Orchestration**](./07_langgraph_and_orchestration.md).