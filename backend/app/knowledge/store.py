"""Enterprise knowledge retriever (the FR-004 Google Drive side + Vector DB).

Two interchangeable backends, chosen automatically:
  * "embeddings" — OpenAI embeddings + cosine (the production path; swap the
    in-memory cosine for Qdrant by setting QDRANT_URL — see `_search_embeddings`).
  * "tfidf"      — pure-Python TF-IDF cosine, zero dependencies, fully offline.

The agent calls `index.search(query)` and gets ranked, snippet-bearing hits
regardless of backend.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..integrations.llm import embed_texts

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CHUNK_WORDS = 90


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _chunk(title: str, content: str) -> list[str]:
    words = content.split()
    chunks: list[str] = []
    for i in range(0, max(len(words), 1), _CHUNK_WORDS):
        body = " ".join(words[i : i + _CHUNK_WORDS])
        chunks.append(f"{title}. {body}".strip())
    return chunks or [title]


@dataclass
class Chunk:
    doc_id: str
    title: str
    doc_type: str
    url: str
    text: str
    tf: dict[str, float] = field(default_factory=dict)
    vec: list[float] = field(default_factory=list)


@dataclass
class Hit:
    doc_id: str
    title: str
    doc_type: str
    url: str
    snippet: str
    score: float


class KnowledgeIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.idf: dict[str, float] = {}
        self.mode: str = "tfidf"

    async def build(self, docs: list[dict]) -> None:
        """docs: [{id,title,doc_type,url,content}]."""
        self.chunks = []
        for d in docs:
            for body in _chunk(d["title"], d["content"]):
                self.chunks.append(
                    Chunk(
                        doc_id=d["id"],
                        title=d["title"],
                        doc_type=d.get("doc_type", ""),
                        url=d.get("url", ""),
                        text=body,
                    )
                )
        self._build_tfidf()

        embeddings = await embed_texts([c.text for c in self.chunks])
        if embeddings:
            for chunk, vec in zip(self.chunks, embeddings):
                chunk.vec = vec
            self.mode = "embeddings"
        else:
            self.mode = "tfidf"

    # ── TF-IDF backend ──────────────────────────────────────────────────────
    def _build_tfidf(self) -> None:
        df: Counter[str] = Counter()
        per_chunk_tokens: list[list[str]] = []
        for chunk in self.chunks:
            tokens = _tokenize(chunk.text)
            per_chunk_tokens.append(tokens)
            df.update(set(tokens))
        n = max(len(self.chunks), 1)
        self.idf = {term: math.log((n + 1) / (cnt + 1)) + 1.0 for term, cnt in df.items()}
        for chunk, tokens in zip(self.chunks, per_chunk_tokens):
            counts = Counter(tokens)
            total = max(len(tokens), 1)
            chunk.tf = {
                term: (cnt / total) * self.idf.get(term, 0.0) for term, cnt in counts.items()
            }

    def _search_tfidf(self, query: str, k: int) -> list[Hit]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        counts = Counter(q_tokens)
        total = max(len(q_tokens), 1)
        q_vec = {t: (c / total) * self.idf.get(t, 0.0) for t, c in counts.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            dot = sum(w * chunk.tf.get(t, 0.0) for t, w in q_vec.items())
            c_norm = math.sqrt(sum(v * v for v in chunk.tf.values())) or 1.0
            scored.append((dot / (q_norm * c_norm), chunk))
        return self._top(scored, k)

    # ── Embeddings backend ──────────────────────────────────────────────────
    async def _search_embeddings(self, query: str, k: int) -> list[Hit]:
        # To use Qdrant instead of in-memory cosine: upsert chunk.vec at build
        # time and replace this block with a Qdrant `search` call.
        q = await embed_texts([query])
        if not q:
            return self._search_tfidf(query, k)
        qv = q[0]
        q_norm = math.sqrt(sum(v * v for v in qv)) or 1.0
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            dot = sum(a * b for a, b in zip(qv, chunk.vec))
            c_norm = math.sqrt(sum(v * v for v in chunk.vec)) or 1.0
            scored.append((dot / (q_norm * c_norm), chunk))
        return self._top(scored, k)

    @staticmethod
    def _top(scored: list[tuple[float, Chunk]], k: int) -> list[Hit]:
        scored.sort(key=lambda x: x[0], reverse=True)
        hits: list[Hit] = []
        seen: set[str] = set()
        for score, chunk in scored:
            if score <= 0:
                continue
            key = chunk.doc_id
            if key in seen:  # one best snippet per document
                continue
            seen.add(key)
            hits.append(
                Hit(
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    doc_type=chunk.doc_type,
                    url=chunk.url,
                    snippet=_snippet(chunk.text),
                    score=round(float(score), 4),
                )
            )
            if len(hits) >= k:
                break
        return hits

    async def search(self, query: str, k: int = 4) -> list[Hit]:
        if self.mode == "embeddings":
            return await self._search_embeddings(query, k)
        return self._search_tfidf(query, k)


def _snippet(text: str, max_chars: int = 280) -> str:
    text = text.strip()
    return text if len(text) <= max_chars else text[:max_chars].rsplit(" ", 1)[0] + "…"


# Module-level singleton, built at app startup.
index = KnowledgeIndex()
