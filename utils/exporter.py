"""Exports a chat session to Markdown or PDF."""

import io
from datetime import datetime


def to_markdown(history_data: dict) -> str:
    lines = [f"# {history_data.get('title', 'Chat')}", ""]
    lines.append(f"_Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append("")
    for msg in history_data.get("messages", []):
        role = "You" if msg["role"] == "user" else "RAGBase"
        lines.append(f"**{role}:**")
        lines.append("")
        lines.append(msg["content"])
        if msg.get("sources"):
            src_names = sorted({s["source"] for s in msg["sources"] if s.get("source")})
            if src_names:
                lines.append("")
                lines.append(f"*Sources: {', '.join(src_names)}*")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def to_pdf_bytes(history_data: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, _sanitize(history_data.get("title", "Chat")))
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    pdf.ln(4)

    for msg in history_data.get("messages", []):
        role = "You" if msg["role"] == "user" else "RAGBase"
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 7, f"{role}:")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _sanitize(msg["content"]))
        if msg.get("sources"):
            src_names = sorted({s["source"] for s in msg["sources"] if s.get("source")})
            if src_names:
                pdf.set_font("Helvetica", "I", 9)
                pdf.multi_cell(0, 5, f"Sources: {', '.join(src_names)}")
        pdf.ln(3)

    out = pdf.output(dest="S")
    if isinstance(out, str):
        out = out.encode("latin-1", errors="replace")
    return bytes(out)


def _sanitize(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")
