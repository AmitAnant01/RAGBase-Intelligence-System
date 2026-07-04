"""
RAGBase PRO - Fully Advanced RAG Chatbot
Author: Amit Anant

Chat with your own documents (PDF/DOCX/PPTX/XLSX/CSV/TXT/MD/HTML/JSON, plus
OCR fallback for scanned PDFs and images), backed by a hybrid BM25 + vector
retriever with MMR diversity reranking, streaming Groq responses, persona
modes, auto-summaries, a Wikipedia-style Research brief generator (with live
images/related links/maps), an analytics dashboard, and chat export to
Markdown/PDF.
"""

import os
import re
import uuid
import json
import time
import hashlib
import requests
from datetime import datetime

from flask import Flask, request, jsonify, render_template, Response, stream_with_context, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import chromadb
from chromadb.utils import embedding_functions

from groq import Groq

from utils.chunking import chunk_text
from utils.extractors import extract_text
from utils.search import hybrid_search
from utils import analytics
from utils.exporter import to_markdown, to_pdf_bytes
from utils.research import fetch_url_text, build_research_brief, wiki_enrich, geocode_location

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
UPLOAD_FOLDER = "uploads"
CHROMA_PATH = "chroma_db"
HISTORY_FOLDER = "chat_history"
META_FOLDER = "doc_meta"
ALLOWED_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "xlsm", "csv", "txt", "md",
    "html", "htm", "json", "png", "jpg", "jpeg", "webp", "bmp",
}
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 4
GROQ_MODEL = "llama-3.3-70b-versatile"
EMBED_MODEL = "all-MiniLM-L6-v2"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CHROMA_PATH, exist_ok=True)
os.makedirs(HISTORY_FOLDER, exist_ok=True)
os.makedirs(META_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB per file

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBED_MODEL
)
collection = chroma_client.get_or_create_collection(
    name="ragbase_docs",
    embedding_function=embedding_fn,
    metadata={"hnsw:space": "cosine"},
)

# In-memory response cache: exact-match query cache, invalidated on any
# upload/delete so answers never go stale relative to the knowledge base.
RESPONSE_CACHE = {}
CACHE_VERSION = {"v": 0}

PERSONAS = {
    "concise": "Answer in 2-4 sentences maximum. Be direct, no fluff.",
    "detailed": "Give a thorough, well-structured answer with headings and bullet points where useful.",
    "eli5": "Explain it like the reader is a curious beginner. Use simple language and one relatable analogy.",
    "exam": "Answer in a crisp exam-ready format: key definition first, then bullet points of important facts to remember.",
    "code": "If the documents contain code or technical specs, prioritize precise technical accuracy, use code blocks, and call out edge cases.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def history_path(session_id: str) -> str:
    return os.path.join(HISTORY_FOLDER, f"{session_id}.json")


def load_history(session_id: str):
    path = history_path(session_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"id": session_id, "title": "New Chat", "created": str(datetime.now()), "messages": []}


def save_history(session_id: str, data: dict):
    with open(history_path(session_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_sessions():
    sessions = []
    for fname in os.listdir(HISTORY_FOLDER):
        if fname.endswith(".json") and not fname.startswith("_"):
            with open(os.path.join(HISTORY_FOLDER, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "id": data["id"],
                "title": data.get("title", "New Chat"),
                "created": data.get("created"),
            })
    sessions.sort(key=lambda x: x["created"], reverse=True)
    return sessions


def get_document_list():
    docs = collection.get(include=["metadatas"])
    seen = {}
    for meta in docs.get("metadatas", []):
        if not meta:
            continue
        fname = meta.get("source")
        if fname not in seen:
            seen[fname] = 0
        seen[fname] += 1
    result = []
    for name, chunks in seen.items():
        meta_info = load_doc_meta(name)
        result.append({
            "name": name,
            "chunks": chunks,
            "summary": meta_info.get("summary", ""),
            "tags": meta_info.get("tags", []),
        })
    return result


def doc_meta_path(filename: str) -> str:
    safe = hashlib.md5(filename.encode()).hexdigest()
    return os.path.join(META_FOLDER, f"{safe}.json")


def save_doc_meta(filename: str, data: dict):
    with open(doc_meta_path(filename), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_doc_meta(filename: str) -> dict:
    path = doc_meta_path(filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def generate_summary_and_tags(text: str) -> dict:
    """One quick Groq call to auto-summarize a freshly uploaded document and tag it."""
    prompt = f"""Summarize the following document in 2-3 sentences, then list 5 short topical tags.
Respond with STRICT JSON only: {{"summary": "...", "tags": ["...", "..."]}}

DOCUMENT (truncated):
{text[:5000]}
"""
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        raw = completion.choices[0].message.content.strip()
        raw = re.sub(r"^```(json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return {"summary": "", "tags": []}


def bump_cache_version():
    CACHE_VERSION["v"] += 1
    RESPONSE_CACHE.clear()


def cache_key(session_id, message, top_k, persona):
    raw = f"{CACHE_VERSION['v']}|{message.strip().lower()}|{top_k}|{persona}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Routes - Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes - Document management
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "files" not in request.files:
        return jsonify({"error": "No file part"}), 400

    files = request.files.getlist("files")
    results = []

    for file in files:
        if file.filename == "" or not allowed_file(file.filename):
            results.append({"name": file.filename, "status": "skipped (unsupported type)"})
            continue

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(save_path)

        try:
            text = extract_text(save_path)
            if not text.strip():
                results.append({"name": filename, "status": "skipped (no extractable text - try OCR-enabled build)"})
                continue

            chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
            ids = [f"{filename}-{uuid.uuid4().hex[:8]}-{i}" for i in range(len(chunks))]
            metadatas = [
                {"source": filename, "chunk_index": i, "uploaded_at": str(datetime.now())}
                for i in range(len(chunks))
            ]
            collection.add(documents=chunks, ids=ids, metadatas=metadatas)

            meta = generate_summary_and_tags(text)
            save_doc_meta(filename, meta)

            analytics.log_upload()
            results.append({"name": filename, "status": "indexed", "chunks": len(chunks), **meta})
        except Exception as e:
            results.append({"name": filename, "status": f"error: {str(e)}"})

    bump_cache_version()
    return jsonify({"results": results, "documents": get_document_list()})


@app.route("/api/documents", methods=["GET"])
def get_documents():
    return jsonify({"documents": get_document_list()})


@app.route("/api/documents/<filename>", methods=["DELETE"])
def delete_document(filename):
    existing = collection.get(include=["metadatas"])
    ids_to_delete = [
        existing["ids"][i]
        for i, meta in enumerate(existing["metadatas"])
        if meta and meta.get("source") == filename
    ]
    if ids_to_delete:
        collection.delete(ids=ids_to_delete)

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    meta_path = doc_meta_path(filename)
    if os.path.exists(meta_path):
        os.remove(meta_path)

    bump_cache_version()
    return jsonify({"status": "deleted", "documents": get_document_list()})


# ---------------------------------------------------------------------------
# Routes - Chat sessions
# ---------------------------------------------------------------------------
@app.route("/api/sessions", methods=["GET"])
def get_sessions():
    return jsonify({"sessions": list_sessions()})


@app.route("/api/sessions", methods=["POST"])
def create_session():
    session_id = uuid.uuid4().hex[:12]
    data = load_history(session_id)
    save_history(session_id, data)
    return jsonify(data)


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    return jsonify(load_history(session_id))


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    path = history_path(session_id)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"status": "deleted"})


@app.route("/api/sessions/<session_id>/rename", methods=["POST"])
def rename_session(session_id):
    payload = request.get_json(force=True)
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    data = load_history(session_id)
    data["title"] = title[:60]
    save_history(session_id, data)
    return jsonify(data)


@app.route("/api/sessions/<session_id>/export", methods=["GET"])
def export_session(session_id):
    fmt = request.args.get("format", "md")
    data = load_history(session_id)

    if fmt == "pdf":
        pdf_bytes = to_pdf_bytes(data)
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={session_id}.pdf"},
        )
    else:
        md_text = to_markdown(data)
        return Response(
            md_text,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={session_id}.md"},
        )


# ---------------------------------------------------------------------------
# Routes - Chat / RAG core
# ---------------------------------------------------------------------------
def build_system_prompt(persona: str) -> str:
    persona_instruction = PERSONAS.get(persona, PERSONAS["detailed"])
    return f"""You are RAGBase Assistant, a helpful AI that answers questions strictly using the
provided document context. Follow these rules:
1. Base your answer primarily on the CONTEXT provided below.
2. If the context does not contain the answer, say so honestly instead of making things up.
3. Cite which source file(s) you used in square brackets, e.g. [source: report.pdf].
4. {persona_instruction}
5. If the user asks something unrelated to the documents (e.g. greetings, general knowledge),
   answer naturally and helpfully without forcing irrelevant context.
"""


def retrieve_context(user_message: str, top_k: int):
    docs, metas, scores = hybrid_search(collection, user_message, top_k=top_k)
    sources = []
    for meta, score in zip(metas, scores):
        sources.append({
            "source": meta.get("source"),
            "chunk_index": meta.get("chunk_index"),
            "relevance": score,
        })
    context_block = "\n\n---\n\n".join(
        f"[Source: {s['source']} | chunk {s['chunk_index']}]\n{c}"
        for c, s in zip(docs, sources)
    ) if docs else "No relevant documents found in the knowledge base."
    confidence = round(sum(s["relevance"] for s in sources) / len(sources), 3) if sources else 0.0
    return context_block, sources, confidence


def build_messages(history_data, context_block, user_message, persona):
    messages = [{"role": "system", "content": build_system_prompt(persona)}]
    for turn in history_data["messages"][-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({
        "role": "user",
        "content": f"CONTEXT:\n{context_block}\n\nQUESTION:\n{user_message}",
    })
    return messages


@app.route("/api/chat", methods=["POST"])
def chat():
    """Non-streaming chat endpoint (kept for simplicity / fallback)."""
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    user_message = payload.get("message", "").strip()
    top_k = int(payload.get("top_k", TOP_K))
    persona = payload.get("persona", "detailed")

    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if not user_message:
        return jsonify({"error": "message is empty"}), 400

    history_data = load_history(session_id)
    start = time.time()

    context_block, sources, confidence = retrieve_context(user_message, top_k)
    messages = build_messages(history_data, context_block, user_message, persona)

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL, messages=messages, temperature=0.3, max_tokens=1024,
        )
        answer = completion.choices[0].message.content
    except Exception as e:
        return jsonify({"error": f"LLM call failed: {str(e)}"}), 500

    elapsed = time.time() - start

    history_data["messages"].append({"role": "user", "content": user_message, "ts": time.time()})
    history_data["messages"].append({
        "role": "assistant", "content": answer, "ts": time.time(),
        "sources": sources, "confidence": confidence,
    })
    if history_data["title"] == "New Chat" and len(history_data["messages"]) <= 2:
        history_data["title"] = user_message[:40] + ("..." if len(user_message) > 40 else "")
    save_history(session_id, history_data)

    analytics.log_query(user_message, sources, elapsed, confidence)

    return jsonify({
        "answer": answer, "sources": sources, "session_title": history_data["title"],
        "confidence": confidence, "response_time": round(elapsed, 2),
    })


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Streaming chat endpoint via Server-Sent-Events-style chunks over a plain response stream."""
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    user_message = payload.get("message", "").strip()
    top_k = int(payload.get("top_k", TOP_K))
    persona = payload.get("persona", "detailed")

    if not session_id or not user_message:
        return jsonify({"error": "session_id and message required"}), 400

    history_data = load_history(session_id)
    ck = cache_key(session_id, user_message, top_k, persona)

    def event(obj):
        return f"data: {json.dumps(obj)}\n\n"

    def generate():
        start = time.time()
        context_block, sources, confidence = retrieve_context(user_message, top_k)

        yield event({"type": "sources", "sources": sources, "confidence": confidence})

        cached = RESPONSE_CACHE.get(ck)
        full_answer = ""

        if cached:
            full_answer = cached
            yield event({"type": "chunk", "text": full_answer})
        else:
            messages = build_messages(history_data, context_block, user_message, persona)
            try:
                stream = groq_client.chat.completions.create(
                    model=GROQ_MODEL, messages=messages, temperature=0.3,
                    max_tokens=1024, stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full_answer += delta
                        yield event({"type": "chunk", "text": delta})
                RESPONSE_CACHE[ck] = full_answer
            except Exception as e:
                yield event({"type": "error", "message": str(e)})
                return

        elapsed = time.time() - start

        history_data["messages"].append({"role": "user", "content": user_message, "ts": time.time()})
        history_data["messages"].append({
            "role": "assistant", "content": full_answer, "ts": time.time(),
            "sources": sources, "confidence": confidence,
        })
        if history_data["title"] == "New Chat" and len(history_data["messages"]) <= 2:
            history_data["title"] = user_message[:40] + ("..." if len(user_message) > 40 else "")
        save_history(session_id, history_data)
        analytics.log_query(user_message, sources, elapsed, confidence)

        yield event({
            "type": "done", "session_title": history_data["title"],
            "response_time": round(elapsed, 2), "cached": bool(cached),
        })

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Routes - Research (paste text / paste a link / upload a file -> a
# Wikipedia-style brief with live images, related links, and a map)
# ---------------------------------------------------------------------------
def looks_like_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.IGNORECASE))


@app.route("/api/research", methods=["POST"])
def research():
    raw_input = (request.form.get("input") or "").strip()
    upload = request.files.get("file")

    title_hint = ""
    content = ""
    source_url = None

    try:
        if upload and upload.filename:
            filename = secure_filename(upload.filename)
            tmp_path = os.path.join(app.config["UPLOAD_FOLDER"], f"_research_{filename}")
            upload.save(tmp_path)
            content = extract_text(tmp_path)
            title_hint = filename
            os.remove(tmp_path)
        elif looks_like_url(raw_input):
            source_url = raw_input
            title_hint, content = fetch_url_text(raw_input)
        elif raw_input:
            content = raw_input
        else:
            return jsonify({"error": "Paste a link, some text, or attach a file."}), 400

        if not content or len(content.strip()) < 40:
            return jsonify({"error": "Couldn't find enough readable text in that input."}), 400

        brief = build_research_brief(groq_client, GROQ_MODEL, content, title_hint=title_hint)

        enrichment = wiki_enrich(brief.get("keywords", []), brief.get("title", ""))
        brief["images"] = enrichment["images"]
        brief["related"] = enrichment["related"]

        brief["map"] = geocode_location(brief["location"]) if brief.get("location") else None
        brief["source_url"] = source_url
        brief["char_count"] = len(content)
        brief["read_minutes"] = max(1, round(len(content.split()) / 200))

        return jsonify(brief)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Couldn't fetch that URL: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Research generation failed: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Routes - Analytics
# ---------------------------------------------------------------------------
@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    return jsonify(analytics.get_summary())


# ---------------------------------------------------------------------------
# Routes - Misc
# ---------------------------------------------------------------------------
@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    bump_cache_version()
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

