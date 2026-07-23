"""Hybrid retriever: dense (vectors) + keyword (BM25) fused with RRF.

Thresholding (no_good_match / confidence band) is anchored on the best *dense*
cosine similarity — an absolute, comparable signal — while recall/ranking uses
Reciprocal Rank Fusion of both arms. This is the anti-hallucination gate: when
the best dense match is below the floor, the agent is told there is no usable
article and must escalate rather than invent a fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.schemas.kb import RetrievalHit, RetrievalResult
from app.services.retrieval.embedder import Embedder
from app.services.retrieval.vector_store import VectorStore

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class IndexedArticle:
    id: str
    title: str
    category: str
    risk_level: str
    content: str
    steps: list = field(default_factory=list)
    required_tools: list = field(default_factory=list)
    applies_to: list = field(default_factory=list)


class HybridRetriever:
    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        *,
        top_k: int = 4,
        dense_k: int = 20,
        keyword_k: int = 20,
        score_floor: float = 0.30,
        rrf_k: int = 60,
    ) -> None:
        self._embedder = embedder
        self._vs = vector_store
        self._top_k = top_k
        self._dense_k = dense_k
        self._keyword_k = keyword_k
        self._score_floor = score_floor
        self._rrf_k = rrf_k

        self._articles: dict[str, IndexedArticle] = {}
        self._bm25 = None
        self._bm25_ids: list[str] = []

    # ------------------------------------------------------------------ #
    def index(self, articles: list[IndexedArticle]) -> None:
        """(Re)build the keyword index and upsert dense vectors."""
        self._articles = {a.id: a for a in articles}
        self._bm25_ids = [a.id for a in articles]

        if articles:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi([tokenize(a.content) for a in articles])
            embeddings = self._embedder.embed_documents([a.content for a in articles])
            metadatas = [
                {"category": a.category, "title": a.title, "risk_level": a.risk_level}
                for a in articles
            ]
            documents = [a.content for a in articles]
            self._vs.upsert([a.id for a in articles], embeddings, metadatas, documents)
            logger.info("kb_indexed", articles=len(articles), vectors=self._vs.count())
        else:
            self._bm25 = None

    @property
    def size(self) -> int:
        return len(self._articles)

    # ------------------------------------------------------------------ #
    def search(self, query: str, category: str | None = None) -> RetrievalResult:
        if not self._articles or not query.strip():
            return RetrievalResult(query=query, hits=[], confidence="none", no_good_match=True)

        # --- dense arm ---
        q_emb = self._embedder.embed_query(query)
        where = {"category": category} if category else None
        dense_hits = self._vs.query(q_emb, self._dense_k, where=where)
        dense_scores = {h.id: h.score for h in dense_hits}
        dense_rank = {h.id: r for r, h in enumerate(dense_hits)}
        best_dense = max(dense_scores.values(), default=0.0)

        # --- keyword arm ---
        keyword_scores: dict[str, float] = {}
        keyword_rank: dict[str, float] = {}
        if self._bm25 is not None:
            raw = self._bm25.get_scores(tokenize(query))
            paired = sorted(zip(self._bm25_ids, raw), key=lambda x: x[1], reverse=True)
            if category:
                paired = [(i, s) for i, s in paired if self._articles[i].category == category]
            paired = [(i, s) for i, s in paired if s > 0][: self._keyword_k]
            max_kw = max((s for _, s in paired), default=0.0)
            for rank, (i, s) in enumerate(paired):
                keyword_scores[i] = (s / max_kw) if max_kw > 0 else 0.0
                keyword_rank[i] = rank

        # --- RRF fusion ---
        candidate_ids = set(dense_rank) | set(keyword_rank)
        fused: dict[str, float] = {}
        for i in candidate_ids:
            score = 0.0
            if i in dense_rank:
                score += 1.0 / (self._rrf_k + dense_rank[i] + 1)
            if i in keyword_rank:
                score += 1.0 / (self._rrf_k + keyword_rank[i] + 1)
            fused[i] = score
        ranked = sorted(candidate_ids, key=lambda i: fused[i], reverse=True)[: self._top_k]

        hits: list[RetrievalHit] = []
        for i in ranked:
            article = self._articles.get(i)
            if article is None:
                continue
            ds = dense_scores.get(i)
            ks = keyword_scores.get(i)
            hits.append(
                RetrievalHit(
                    article_id=i,
                    title=article.title,
                    category=article.category,
                    risk_level=article.risk_level,
                    score=round(ds if ds is not None else (ks or 0.0), 4),
                    dense_score=round(ds, 4) if ds is not None else None,
                    keyword_score=round(ks, 4) if ks is not None else None,
                    steps=article.steps,
                    required_tools=article.required_tools,
                    snippet=article.content[:240],
                )
            )

        no_good = best_dense < self._score_floor
        if best_dense >= 0.60:
            confidence = "high"
        elif best_dense >= 0.45:
            confidence = "medium"
        elif best_dense >= self._score_floor:
            confidence = "low"
        else:
            confidence = "none"

        return RetrievalResult(
            query=query, hits=hits, confidence=confidence, no_good_match=no_good
        )
