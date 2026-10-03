"""
Semantic search over crawled content.

Every chunk's embedding is held in memory and scored against the query (exact search).
At this corpus size (thousands of chunks, 384 dimensions) that takes milliseconds and needs
no vector database. The index reloads itself when the crawler service changes the table.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List

import numpy as np
from sqlmodel import Session, func, select

from db import engine
from embeddings import EMBEDDING_DIM, embeddings, vector_from_bytes
from models import CrawledDocument

logger = logging.getLogger(__name__)


class SearchIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._version = None
        self._ids: List[str] = []
        self._matrix = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    def _table_version(self, session: Session):
        return session.exec(
            select(func.count(CrawledDocument.id), func.max(CrawledDocument.updated_at))
            .where(CrawledDocument.embedding.isnot(None))
        ).one()

    def _refresh(self, session: Session):
        version = self._table_version(session)
        if version == self._version:
            return
        rows = session.exec(
            select(CrawledDocument.id, CrawledDocument.embedding)
            .where(CrawledDocument.embedding.isnot(None))
        ).all()
        vectors = [vector_from_bytes(row[1]) for row in rows]
        valid = [i for i, v in enumerate(vectors) if v.shape == (EMBEDDING_DIM,)]
        if len(valid) < len(rows):
            logger.warning(f"Skipping {len(rows) - len(valid)} chunks with embeddings from a different model; re-crawl to fix")
        self._ids = [rows[i][0] for i in valid]
        self._matrix = np.stack([vectors[i] for i in valid]) if valid else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        self._version = version
        logger.info(f"Search index loaded: {len(self._ids)} chunks")

    def search_sync(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        start = time.time()
        with self._lock, Session(engine) as session:
            self._refresh(session)
            if not self._ids:
                logger.warning("Search index is empty; has the crawler run yet?")
                return []
            scores = self._matrix @ embeddings.embed_query_array(query)  # cosine similarity: vectors are normalized
            top = np.argsort(-scores)[:limit]
            top_ids = [self._ids[i] for i in top]
            rows = {doc.id: doc for doc in session.exec(select(CrawledDocument).where(CrawledDocument.id.in_(top_ids))).all()}

        results = []
        for i in top:
            doc = rows.get(self._ids[i])
            if doc is None:
                continue  # removed by the crawler since the index loaded
            title = doc.title
            if doc.total_chunks and doc.total_chunks > 1:
                title = f"{doc.title} (Section {doc.chunk_index + 1} of {doc.total_chunks})"
            results.append({
                'title': title,
                'content': doc.content,
                'url': doc.url,
                'score': float(scores[i]),
                'content_type': doc.content_type,
                'chunk_index': doc.chunk_index,
                'total_chunks': doc.total_chunks,
            })
        logger.info(f"Search '{query[:60]}': {len(results)} results from {len(self._ids)} chunks, {(time.time() - start) * 1000:.0f}ms")
        return results

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.search_sync, query, limit)


search_index = SearchIndex()
