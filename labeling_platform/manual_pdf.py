"""Build a downloadable PDF from the simple scoring user manual markdown."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Iterable, Tuple

from fpdf import FPDF

LineStyle = str  # h1 | h2 | h3 | body | bullet | blank | image


def _ascii_safe(text: str) -> str:
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2192": "->",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u2026": "...",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.encode("latin-1", "replace").decode("latin-1")


def _iter_manual_lines(markdown: str) -> Iterable[Tuple[LineStyle, str]]:
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            yield "blank", ""
            continue
        if re.match(r"^\|[-:\s|]+\|$", line):
            continue
        if line.startswith("# "):
            yield "h1", _ascii_safe(line[2:].strip())
        elif line.startswith("## "):
            yield "h2", _ascii_safe(line[3:].strip())
        elif line.startswith("### "):
            yield "h3", _ascii_safe(line[4:].strip())
        elif line.startswith("- "):
            yield "bullet", _ascii_safe(line[2:].strip())
        elif re.match(r"^\d+\.\s", line):
            yield "bullet", _ascii_safe(line.strip())
        elif line.startswith(">"):
            yield "body", _ascii_safe(line.lstrip("> ").strip())
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            yield "body", _ascii_safe(" | ".join(c for c in cells if c))
        elif line.startswith("!["):
            yield "image", line.strip()
        else:
            yield "body", _ascii_safe(line.strip())


def _write_multiline(pdf: FPDF, text: str, *, size: int = 10, bold: bool = False, line_height: float = 5) -> None:
    if not text.strip():
        return
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.multi_cell(pdf.epw, line_height, text)
    pdf.set_font("Helvetica", size=10)


def build_manual_pdf_bytes(markdown: str, project_root: Path) -> bytes:
    pdf = FPDF(format="letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)

    for style, text in _iter_manual_lines(markdown):
        if style == "blank":
            pdf.ln(3)
            continue
        if style == "image":
            match = re.search(r"!\[.*?\]\((.*?)\)", text)
            if not match:
                continue
            rel = match.group(1).replace("\\", "/")
            img_path = project_root / rel
            if img_path.exists() and img_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                pdf.ln(4)
                pdf.set_x(pdf.l_margin)
                try:
                    pdf.image(str(img_path), w=min(170, pdf.epw))
                except Exception:
                    _write_multiline(pdf, f"[Image: {img_path.name}]")
                pdf.ln(4)
            continue
        if style == "h1":
            pdf.ln(4)
            _write_multiline(pdf, text, size=16, bold=True, line_height=8)
            pdf.ln(2)
        elif style == "h2":
            pdf.ln(3)
            _write_multiline(pdf, text, size=13, bold=True, line_height=7)
            pdf.ln(1)
        elif style == "h3":
            pdf.ln(2)
            _write_multiline(pdf, text, size=11, bold=True, line_height=6)
        elif style == "bullet":
            _write_multiline(pdf, f"- {text}")
        else:
            _write_multiline(pdf, text)

    out = BytesIO()
    pdf.output(out)
    return out.getvalue()
