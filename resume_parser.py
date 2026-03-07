"""resume_parser.py — Parse resumes from PDF, DOCX, TXT, or Typst format."""
from __future__ import annotations

import re
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".typ"}


def parse_resume(file_path: str | Path) -> str:
    """Parse a resume file and return its plain-text content.

    Supported formats: PDF, DOCX/DOC, TXT/MD, Typst (.typ)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in (".docx", ".doc"):
        return _parse_docx(path)
    if suffix == ".typ":
        return _parse_typst(path)
    # .txt / .md / anything else → plain text
    return _parse_text(path)


# ---------------------------------------------------------------------------
# Format-specific parsers
# ---------------------------------------------------------------------------

def _parse_pdf(path: Path) -> str:
    # Try pymupdf first (faster, better layout)
    try:
        import fitz  # type: ignore  (pymupdf)
        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(pages).strip()
    except ImportError:
        pass

    # Fallback: pdfminer.six
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        return extract_text(str(path)).strip()
    except ImportError:
        pass

    raise ImportError(
        "PDF parsing requires pymupdf or pdfminer.six.\n"
        "Install with: pip install pymupdf  OR  pip install pdfminer.six"
    )


def _parse_docx(path: Path) -> str:
    try:
        from docx import Document  # type: ignore  (python-docx)
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip()
    except ImportError:
        raise ImportError(
            "DOCX parsing requires python-docx.\n"
            "Install with: pip install python-docx"
        )


def _parse_typst(path: Path) -> str:
    """Extract readable text from a Typst source file.

    Typst is a markup/typesetting language. We strip the most common
    command syntax and return the prose + structural content.
    """
    raw = path.read_text(encoding="utf-8", errors="ignore")

    # Remove block-level Typst commands: #show, #set, #let, #import
    raw = re.sub(r"#(show|set|let|import)[^\n]*\n", "\n", raw)

    # Remove inline function calls like #h(1fr), #v(-3pt), #chiline()
    raw = re.sub(r"#\w+\([^)]*\)", "", raw)

    # Remove remaining # directives that are single tokens
    raw = re.sub(r"#\w+", "", raw)

    # Remove Typst link syntax: #link("url")[text] → text
    raw = re.sub(r'#link\("[^"]*"\)\[([^\]]*)\]', r"\1", raw)

    # Convert bold *text* markers to plain text
    raw = re.sub(r"\*([^*]+)\*", r"\1", raw)

    # Remove emphasis _text_
    raw = re.sub(r"_([^_]+)_", r"\1", raw)

    # Collapse multiple blank lines
    raw = re.sub(r"\n{3,}", "\n\n", raw)

    return raw.strip()


def _parse_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


# ---------------------------------------------------------------------------
# File-object variant (for Streamlit's UploadedFile)
# ---------------------------------------------------------------------------

def parse_resume_bytes(filename: str, data: bytes) -> str:
    """Parse a resume from raw bytes (e.g. from Streamlit file uploader)."""
    import tempfile, os

    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        return parse_resume(tmp_path)
    finally:
        os.unlink(tmp_path)
