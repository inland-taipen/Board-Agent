"""Hybrid retrieval index: BM25 lexical + optional dense vectors.

Lexical retrieval is the primary channel and is always available. Board packs
are dense with proper nouns, statute references, covenant names and figures
("Ind AS 116", "DSCR", "Q3 FY26") where exact-term matching outperforms
embeddings, and BM25 adds no model download to a client-hosted deployment.

Dense retrieval is optional (`pip install -e '.[dense]'`, BOARDLENS_DENSE_RETRIEVAL=true)
and catches the paraphrase cases lexical search misses - "attrition in the
sales organisation" against "headcount churn, commercial function". When
enabled, the two rankings are fused with Reciprocal Rank Fusion, which needs
no score calibration between the two very different scoring scales.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np

from .chunker import Chunk

_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:[.,]\d+)*%?")

# Deliberately short: board English is formulaic, and dropping domain words
# like "risk", "control" or "board" would gut the very queries we run.
_STOPWORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "their", "there", "here", "we", "our", "you", "your", "they", "he", "she", "his", "her", "him", "them", "i", "me", "my", "will", "would", "shall", "should", "can", "could", "may", "might", "must", "do", "does", "did", "done", "have", "has", "had", "having", "not", "no", "nor", "so", "such", "into", "over", "under", "again", "further", "once", "during", "about", "against", "between", "through", "above", "below", "up", "down", "out", "off"]
)

_K1 = 1.4
_B = 0.75
_RRF_K = 60


def tokenize(text: str) -> list[str]:
    return [
        t.lower()
        for t in _TOKEN.findall(text)
        if len(t) > 1 and t.lower() not in _STOPWORDS
    ]


@dataclass
class Hit:
    chunk: Chunk
    score: float
    channel: str  # "lexical" | "dense" | "hybrid"


class BM25:
    """Okapi BM25 over an in-memory inverted index."""

    def __init__(self) -> None:
        self.postings: dict[str, dict[int, int]] = {}
        self.lengths: list[int] = []
        self.avg_len: float = 0.0
        self.n_docs: int = 0

    def build(self, texts: list[str]) -> None:
        self.postings = {}
        self.lengths = []
        for doc_id, text in enumerate(texts):
            counts = Counter(tokenize(text))
            self.lengths.append(sum(counts.values()) or 1)
            for term, freq in counts.items():
                self.postings.setdefault(term, {})[doc_id] = freq
        self.n_docs = len(texts)
        self.avg_len = (sum(self.lengths) / self.n_docs) if self.n_docs else 0.0

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if not self.n_docs:
            return []
        scores = np.zeros(self.n_docs, dtype=np.float32)
        for term in set(tokenize(query)):
            posting = self.postings.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for doc_id, freq in posting.items():
                norm = 1 - _B + _B * (self.lengths[doc_id] / self.avg_len)
                scores[doc_id] += idf * (freq * (_K1 + 1)) / (freq + _K1 * norm)

        top = np.argsort(-scores)[: top_k * 2]
        return [(int(i), float(scores[i])) for i in top if scores[i] > 0][:top_k]

    def to_dict(self) -> dict:
        return {
            "postings": {t: {str(d): f for d, f in p.items()} for t, p in self.postings.items()},
            "lengths": self.lengths,
            "avg_len": self.avg_len,
            "n_docs": self.n_docs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BM25:
        obj = cls()
        obj.postings = {t: {int(d): f for d, f in p.items()} for t, p in data["postings"].items()}
        obj.lengths = data["lengths"]
        obj.avg_len = data["avg_len"]
        obj.n_docs = data["n_docs"]
        return obj


class DenseEncoder:
    """Lazy wrapper around sentence-transformers.

    Import is deferred so the default install never pays for torch, and a
    missing extra fails with an actionable message instead of an ImportError
    at module load.
    """

    _cache: ClassVar[dict[str, DenseEncoder]] = {}

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Dense retrieval is enabled (BOARDLENS_DENSE_RETRIEVAL=true) but "
                "sentence-transformers is not installed. Run: pip install -e '.[dense]' "
                "or set BOARDLENS_DENSE_RETRIEVAL=false to use lexical retrieval only."
            ) from exc
        self.model = SentenceTransformer(model_name)

    @classmethod
    def get(cls, model_name: str) -> DenseEncoder:
        if model_name not in cls._cache:
            cls._cache[model_name] = cls(model_name)
        return cls._cache[model_name]

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(
            texts, batch_size=32, convert_to_numpy=True, normalize_embeddings=True
        )
        return vectors.astype(np.float32)


class PackIndex:
    """Retrieval index over one board pack, persisted under the pack's directory."""

    def __init__(self, chunks: list[Chunk], *, dense_model: str | None = None) -> None:
        self.chunks = chunks
        self.by_id = {c.chunk_id: c for c in chunks}
        self.dense_model = dense_model
        self.bm25 = BM25()
        self.vectors: np.ndarray | None = None

    # -- build / persist -----------------------------------------------------

    def build(self) -> PackIndex:
        texts = [self._indexed_text(c) for c in self.chunks]
        self.bm25.build(texts)
        if self.dense_model:
            self.vectors = DenseEncoder.get(self.dense_model).encode(texts)
        return self

    @staticmethod
    def _indexed_text(chunk: Chunk) -> str:
        # Heading and source kind are repeated into the indexed text so that a
        # query like "internal audit findings" retrieves audit-report chunks
        # even when the body never repeats the word "audit".
        parts = [chunk.doc_name, chunk.doc_kind.replace("_", " ")]
        if chunk.heading:
            parts.append(chunk.heading)
        parts.append(chunk.text)
        return "\n".join(parts)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "dense_model": self.dense_model,
            "bm25": self.bm25.to_dict(),
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "doc_name": c.doc_name,
                    "doc_kind": c.doc_kind,
                    "page": c.page,
                    "locator": c.locator,
                    "text": c.text,
                    "heading": c.heading,
                    "kind": c.kind,
                    "meta": c.meta,
                }
                for c in self.chunks
            ],
        }
        (directory / "index.json").write_text(json.dumps(payload), encoding="utf-8")
        if self.vectors is not None:
            np.save(directory / "vectors.npy", self.vectors)

    @classmethod
    def load(cls, directory: Path) -> PackIndex:
        payload = json.loads((directory / "index.json").read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in payload["chunks"]]
        index = cls(chunks, dense_model=payload.get("dense_model"))
        index.bm25 = BM25.from_dict(payload["bm25"])
        vector_path = directory / "vectors.npy"
        if vector_path.exists():
            index.vectors = np.load(vector_path)
        return index

    # -- query ---------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 12,
        doc_kinds: list[str] | None = None,
    ) -> list[Hit]:
        allowed: set[int] | None = None
        if doc_kinds:
            wanted = set(doc_kinds)
            allowed = {i for i, c in enumerate(self.chunks) if c.doc_kind in wanted}
            if not allowed:
                allowed = None  # Filter matched nothing; fall back to the whole pack.

        pool = top_k * 4
        lexical = self.bm25.search(query, pool)
        if allowed is not None:
            lexical = [(i, s) for i, s in lexical if i in allowed]

        if self.vectors is None or not self.dense_model:
            return [
                Hit(self.chunks[i], score, "lexical") for i, score in lexical[:top_k]
            ]

        q_vec = DenseEncoder.get(self.dense_model).encode([query])[0]
        sims = self.vectors @ q_vec
        order = np.argsort(-sims)
        dense: list[tuple[int, float]] = []
        for i in order:
            i = int(i)
            if allowed is not None and i not in allowed:
                continue
            dense.append((i, float(sims[i])))
            if len(dense) >= pool:
                break

        return self._fuse(lexical, dense, top_k)

    def _fuse(
        self,
        lexical: list[tuple[int, float]],
        dense: list[tuple[int, float]],
        top_k: int,
    ) -> list[Hit]:
        """Reciprocal Rank Fusion - rank-based, so the two scales never need calibrating."""
        fused: dict[int, float] = {}
        for rank, (idx, _) in enumerate(lexical):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, (idx, _) in enumerate(dense):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (_RRF_K + rank + 1)

        ranked = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]
        return [Hit(self.chunks[i], score, "hybrid") for i, score in ranked]

    def get(self, chunk_id: str) -> Chunk | None:
        return self.by_id.get(chunk_id)
