"""
Local text embeddings, shared by the crawlers and search.

Runs Snowflake Arctic Embed S on the CPU through fastembed, so indexing and search need no API key.
Chosen by benchmarking candidate models on real bradley.edu content (eval/embedding-benchmark/).
"""

import asyncio
import os
import threading
from typing import List

import numpy as np
from langchain_core.embeddings import Embeddings

EMBEDDING_MODEL = "snowflake/snowflake-arctic-embed-s"
EMBEDDING_DIM = 384
# Arctic Embed is trained with this instruction on queries only; documents are embedded as-is
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# The Docker image downloads the model at build time into this directory
MODEL_CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR")


class LocalEmbeddings(Embeddings):
    """LangChain embeddings interface over fastembed; vectors are L2-normalized float32."""

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(EMBEDDING_MODEL, cache_dir=MODEL_CACHE_DIR)
            return self._model

    def _embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        vectors = np.array(list(self._get_model().embed(texts, batch_size=32)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self._embed([QUERY_PREFIX + text])[0].tolist()

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.embed_query, text)

    # Compact storage helpers used by the crawlers and search index
    def embed_documents_bytes(self, texts: List[str]) -> List[bytes]:
        return [vector.tobytes() for vector in self._embed(texts)]

    def embed_query_array(self, text: str) -> np.ndarray:
        return self._embed([QUERY_PREFIX + text])[0]


embeddings = LocalEmbeddings()


def vector_from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
