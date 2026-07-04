# RAGBase PRO — Advanced RAG Chatbot

Chat with your own documents. Upload files, ask questions, get grounded, cited,
streaming answers — plus a stack of features most RAG demos don't bother with.

## What's new in PRO

**Retrieval**
- Hybrid search: vector similarity (Chroma) + BM25 keyword search, fused with
  Reciprocal Rank Fusion, then diversified with MMR so you don't get five
  near-duplicate chunks from the same paragraph.
- Confidence score shown per answer, based on retrieval relevance.

**File support**
- PDF, DOCX, PPTX, XLSX/XLSM, CSV, TXT, MD, HTML, JSON — and images/scanned
  PDFs via OCR (auto-falls back gracefully if Tesseract isn't installed on
  your machine).

**Chat**
- Live token-by-token streaming responses.
- Five response personas: Detailed, Concise, ELI5, Exam Prep, Technical.
- Exact-match response caching (instant replies for repeated questions,
  auto-invalidated whenever your knowledge base changes).
- Voice input (mic button, Web Speech API) and voice output (toggleable
  text-to-speech read-aloud).
- Click any source citation chip to see which chunk it came from.
- Export any chat to Markdown or PDF.
- Rename chat sessions.

**Documents**
- Auto-generated 2-3 sentence summary + topic tags for every upload (one
  extra Groq call at index time).
- Drag-and-drop multi-file upload.

**Quiz & Flashcards**
- Generate multiple-choice quizzes or flashcards on demand, grounded in your
  documents, optionally scoped to a topic.

**Analytics dashboard**
- Total queries, average response time, files uploaded.
- Top referenced documents (which files actually get used).
- Recent query log with response time + confidence.

**Knowledge Map**
- A 2D PCA scatter plot of every chunk's embedding, colored by source file —
  a visual sense of how your knowledge base clusters by topic.

**UI**
- Dark / light theme toggle, dark navy-violet-cyan palette by default.
- Tabbed layout: Chat / Analytics / Quiz / Knowledge Map.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your free Groq API key from https://console.groq.com/keys
python app.py
```

Open `http://localhost:5000`.

### Optional: OCR for scanned PDFs / images
OCR uses `pytesseract` + `pdf2image`, which need the Tesseract and Poppler
binaries installed on your system (not just the Python packages). If they
aren't installed, scanned documents simply skip OCR instead of crashing —
everything else keeps working.

- Windows: install Tesseract (UB-Mannheim build) and Poppler for Windows,
  add both to PATH.
- Linux: `sudo apt install tesseract-ocr poppler-utils`
- macOS: `brew install tesseract poppler`

Then also `pip install pdf2image`.

## Project structure

```
RAGBase/
├── app.py                  # Flask app + all API routes
├── utils/
│   ├── extractors.py       # multi-format text extraction (+ OCR)
│   ├── chunking.py         # sentence-aware overlapping chunker
│   ├── search.py           # hybrid BM25 + vector + MMR retrieval
│   ├── analytics.py        # local usage tracking (JSON file)
│   ├── quiz.py             # quiz / flashcard generation via Groq
│   ├── exporter.py         # chat export to Markdown / PDF
│   └── visualize.py        # PCA embedding scatter plot (PNG)
├── templates/index.html
├── static/style.css
├── static/script.js
├── chroma_db/               # persistent vector store (auto-created)
├── chat_history/            # per-session JSON transcripts + analytics
├── doc_meta/                # per-document summary/tags cache
└── uploads/                 # original uploaded files
```

## Notes

- Everything runs locally except the LLM call itself (Groq's free API) and
  the initial download of the sentence-transformers embedding model.
- The response cache, chat history, and document index all live on disk, so
  restarting the server keeps your knowledge base and past chats intact.
