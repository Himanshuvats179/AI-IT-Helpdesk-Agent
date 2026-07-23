"""Vector store abstraction + ChromaDB and in-memory implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class VectorHit:
    id: str
    score: float  # cosine similarity in [-1, 1] (higher = closer)
    metadata: dict[str, Any] = field(default_factory=dict)
    document: str = ""


@runtime_checkable
class VectorStore(Protocol):
    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None: ...

    def query(
        self, embedding: list[float], k: int, where: dict[str, Any] | None = None
    ) -> list[VectorHit]: ...

    def count(self) -> int: ...

    def reset(self) -> None: ...


class ChromaVectorStore:
    """Persistent vector store backed by ChromaDB (cosine space).

    Embeddings are always supplied externally (by our Embedder) so Chroma never
    needs its own embedding function — the Embedder remains authoritative.
    """

    def __init__(self, path: str, collection_name: str) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, ids, embeddings, metadatas, documents) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents
        )

    def query(self, embedding, k, where=None) -> list[VectorHit]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(k, self._collection.count()),
            where=where or None,
            include=["metadatas", "documents", "distances"],
        )
        hits: list[VectorHit] = []
        ids = (result.get("ids") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        for i, _id in enumerate(ids):
            distance = dists[i] if i < len(dists) else 1.0
            hits.append(
                VectorHit(
                    id=_id,
                    score=1.0 - float(distance),  # cosine distance -> similarity
                    metadata=metas[i] if i < len(metas) else {},
                    document=docs[i] if i < len(docs) else "",
                )
            )
        return hits

    def count(self) -> int:
        return int(self._collection.count())

    def reset(self) -> None:
        name = self._collection.name
        meta = self._collection.metadata
        self._client.delete_collection(name)
        self._collection = self._client.get_or_create_collection(name=name, metadata=meta)


class InMemoryVectorStore:
    """Lightweight cosine vector store for tests (no external deps)."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []
        self._metadatas: list[dict[str, Any]] = []
        self._documents: list[str] = []
        self._id_to_idx: dict[str, int] = {}  # O(1) lookups -> O(n) reindex

    def upsert(self, ids, embeddings, metadatas, documents) -> None:
        for i, _id in enumerate(ids):
            idx = self._id_to_idx.get(_id)
            if idx is not None:
                self._vectors[idx] = embeddings[i]
                self._metadatas[idx] = metadatas[i]
                self._documents[idx] = documents[i]
            else:
                self._id_to_idx[_id] = len(self._ids)
                self._ids.append(_id)
                self._vectors.append(embeddings[i])
                self._metadatas.append(metadatas[i])
                self._documents.append(documents[i])

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        import math

        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def query(self, embedding, k, where=None) -> list[VectorHit]:
        scored: list[VectorHit] = []
        for i, _id in enumerate(self._ids):
            meta = self._metadatas[i]
            if where and any(meta.get(key) != val for key, val in where.items()):
                continue
            scored.append(
                VectorHit(
                    id=_id,
                    score=self._cosine(embedding, self._vectors[i]),
                    metadata=meta,
                    document=self._documents[i],
                )
            )
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def count(self) -> int:
        return len(self._ids)

    def reset(self) -> None:
        self._ids.clear()
        self._vectors.clear()
        self._metadatas.clear()
        self._documents.clear()
        self._id_to_idx.clear()
