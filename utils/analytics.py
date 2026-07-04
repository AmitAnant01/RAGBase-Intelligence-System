"""Lightweight local analytics tracker - no external services, just a JSON file."""

import os
import json
import time

ANALYTICS_PATH = os.path.join("chat_history", "_analytics.json")


def _load():
    if os.path.exists(ANALYTICS_PATH):
        with open(ANALYTICS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "total_queries": 0,
        "total_response_time": 0.0,
        "doc_hits": {},
        "queries_log": [],
        "uploads": 0,
    }


def _save(data):
    os.makedirs(os.path.dirname(ANALYTICS_PATH), exist_ok=True)
    with open(ANALYTICS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def log_query(question: str, sources: list, response_time: float, confidence: float):
    data = _load()
    data["total_queries"] += 1
    data["total_response_time"] += response_time
    for s in sources:
        name = s.get("source")
        if name:
            data["doc_hits"][name] = data["doc_hits"].get(name, 0) + 1
    data["queries_log"].append({
        "q": question[:120],
        "ts": time.time(),
        "response_time": round(response_time, 2),
        "confidence": confidence,
        "num_sources": len(sources),
    })
    data["queries_log"] = data["queries_log"][-200:]  # cap log size
    _save(data)


def log_upload():
    data = _load()
    data["uploads"] += 1
    _save(data)


def get_summary():
    data = _load()
    avg_time = (data["total_response_time"] / data["total_queries"]) if data["total_queries"] else 0
    top_docs = sorted(data["doc_hits"].items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "total_queries": data["total_queries"],
        "avg_response_time": round(avg_time, 2),
        "uploads": data["uploads"],
        "top_documents": [{"name": k, "hits": v} for k, v in top_docs],
        "recent_queries": list(reversed(data["queries_log"][-15:])),
    }
