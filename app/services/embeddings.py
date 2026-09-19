from typing import List
from openai import OpenAI, RateLimitError
from config import config

# Generates deterministic fallback embeddings when the remote provider is unavailable.
def _local_embed_texts(texts: List[str]) -> List[List[float]]:
    # Deterministic fallback embeddings when the remote provider is unavailable.
    dim = 2048
    vectors: List[List[float]] = []
    for text in texts:
        values = [0.0] * dim
        for idx, char in enumerate(text):
            values[idx % dim] += float(ord(char))
        total = sum(values) or 1.0
        vectors.append([val / total for val in values])
    return vectors

def _local_embed_query(text: str) -> List[float]:
    return _local_embed_texts([text])[0]

def get_client() -> OpenAI:
    # Build an OpenRouter-compatible OpenAI client from env config.
    api_key = config.OPENROUTER_API_KEY
    base_url = config.OPENROUTER_BASE_URL
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. "
            "Set it in your environment or .env file."
        )
    return OpenAI(api_key=api_key, base_url=base_url)

def embed_texts(texts: List[str]) -> List[List[float]]:
    # Generate embeddings for multiple documents in one request.
    client = get_client()
    try:
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=texts,
            encoding_format="float",
        )
        # Preserve original order in case the response is reordered.
        data = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in data]
    except Exception:
        return _local_embed_texts(texts)

def embed_query(text: str) -> List[float]:
    # Generate an embedding for a single user query.
    client = get_client()
    try:
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=text,
            encoding_format="float",
        )
        return response.data[0].embedding
    except Exception:
        return _local_embed_query(text)