"""Zero-dependency retrieval: keyword (BM25-style) search over document chunks.

Good enough for a hackathon demo of "chat with your documents" without embeddings or a vector DB.
If the organisers give an embeddings endpoint, swap `search()` for cosine similarity.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.core.files import chunk_text

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an and or of to in on for is are was were be by with as at from that this it its".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


class DocIndex:
    def __init__(self):
        self.chunks: list[dict] = []  # {"source": str, "text": str, "tf": Counter, "len": int}

    def add(self, source: str, text: str):
        for c in chunk_text(text):
            toks = _tokens(c)
            self.chunks.append({"source": source, "text": c, "tf": Counter(toks), "len": len(toks)})

    def search(self, query: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []
        q = set(_tokens(query))
        n = len(self.chunks)
        avg = sum(c["len"] for c in self.chunks) / n or 1
        df = {t: sum(1 for c in self.chunks if t in c["tf"]) for t in q}
        scored = []
        for c in self.chunks:
            s = 0.0
            for t in q:
                if t in c["tf"]:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    tf = c["tf"][t]
                    s += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * c["len"] / avg))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]

    def context_for(self, query: str, k: int = 4) -> str:
        hits = self.search(query, k)
        return "\n\n---\n\n".join(f"[Source: {h['source']}]\n{h['text']}" for h in hits)
