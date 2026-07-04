"""
Hybrid retrieval: combines Chroma's vector similarity search with a classic
BM25 keyword search over the same corpus, fuses the two ranked lists, then
applies Maximal Marginal Relevance (MMR) so the final context isn't five
near-duplicate chunks from the same paragraph.
"""

import re
import numpy as np
from rank_bm25 import BM25Okapi


def _tokenize(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())


def _reciprocal_rank_fusion(rank_lists, k=60):
    """Standard RRF: score = sum(1 / (k + rank)) across each ranked list."""
    scores = {}
    for ranked_ids in rank_lists:
        for rank, doc_id in enumerate(ranked_ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def hybrid_search(collection, query: str, top_k: int = 4, fetch_k: int = 20):
    """
    Returns (documents, metadatas, scores) for the top_k most relevant chunks,
    fusing vector search + BM25, then diversifying with MMR.
    """
    count = collection.count()
    if count == 0:
        return [], [], []

    fetch_k = min(fetch_k, count)

    # ---- Vector search (Chroma) ----
    vec_results = collection.query(
        query_texts=[query],
        n_results=fetch_k,
        include=["documents", "metadatas", "distances", "embeddings"],
    )
    vec_docs = vec_results["documents"][0]
    vec_metas = vec_results["metadatas"][0]
    vec_ids = vec_results["ids"][0]
    vec_embeds = vec_results["embeddings"][0]
    vec_distances = vec_results["distances"][0]

    if not vec_docs:
        return [], [], []

    # ---- BM25 over the fetched candidate pool (cheap re-scoring, not full corpus scan) ----
    tokenized = [_tokenize(d) for d in vec_docs]
    bm25 = BM25Okapi(tokenized)
    bm25_scores = bm25.get_scores(_tokenize(query))
    bm25_rank = list(np.argsort(bm25_scores)[::-1])

    vec_rank = list(range(len(vec_docs)))  # already sorted by vector similarity

    fused = _reciprocal_rank_fusion([vec_rank, bm25_rank])
    order = sorted(range(len(vec_docs)), key=lambda i: fused.get(i, 0), reverse=True)

    # ---- MMR diversity reranking over the fused order ----
    lambda_mult = 0.7
    selected = []
    candidates = order[:fetch_k]
    query_vec = np.array(vec_embeds[candidates[0]]) if candidates else None

    embeds_arr = np.array([vec_embeds[i] for i in candidates])
    if embeds_arr.size == 0:
        return [], [], []

    def cos_sim(a, b):
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
        return float(np.dot(a, b) / denom)

    remaining = list(candidates)
    # relevance score = fused RRF score (normalized)
    max_fused = max(fused.values()) if fused else 1.0
    rel_scores = {i: fused.get(i, 0) / max_fused for i in candidates}

    while remaining and len(selected) < top_k:
        if not selected:
            best = max(remaining, key=lambda i: rel_scores[i])
        else:
            def mmr_score(i):
                relevance = rel_scores[i]
                diversity = max(cos_sim(vec_embeds[i], vec_embeds[j]) for j in selected)
                return lambda_mult * relevance - (1 - lambda_mult) * diversity
            best = max(remaining, key=mmr_score)
        selected.append(best)
        remaining.remove(best)

    docs = [vec_docs[i] for i in selected]
    metas = [vec_metas[i] for i in selected]
    scores = [round(max(0.0, 1 - vec_distances[i]), 3) for i in selected]
    return docs, metas, scores
