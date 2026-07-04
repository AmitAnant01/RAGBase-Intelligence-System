"""Simple recursive-ish text chunker with overlap, no extra dependencies needed."""

import re


def _split_into_sentences(text: str):
    return re.split(r"(?<=[.!?])\s+", text)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120):
    """
    Splits text into overlapping chunks, trying to break on sentence boundaries
    so retrieval context stays coherent.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    sentences = _split_into_sentences(text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            # start new chunk, carrying over overlap from the end of previous chunk
            overlap_text = current[-overlap:] if current else ""
            current = f"{overlap_text} {sentence}".strip()

    if current:
        chunks.append(current)

    # Fallback: if a single sentence is longer than chunk_size, hard-split it
    final_chunks = []
    for c in chunks:
        if len(c) <= chunk_size * 1.5:
            final_chunks.append(c)
        else:
            for i in range(0, len(c), chunk_size - overlap):
                final_chunks.append(c[i:i + chunk_size])

    return final_chunks
