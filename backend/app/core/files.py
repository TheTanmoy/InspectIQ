"""Turn uploaded files into text the LLM can read. Handles PDF, DOCX, CSV, XLSX, TXT/MD/JSON."""
from __future__ import annotations

import io
import json

MAX_CHARS = 60_000  # keep prompts within context; adjust to the provided model


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join(f"[Page {i+1}]\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))
        elif name.endswith(".docx"):
            import docx  # python-docx
            text = "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
        elif name.endswith((".csv", ".xlsx", ".xls")):
            text = dataframe_summary(load_table(filename, data))
        elif name.endswith(".json"):
            text = json.dumps(json.loads(data), indent=2)
        else:
            text = data.decode("utf-8", errors="ignore")
    except ImportError as e:
        return f"[Could not read {filename}: missing package {e.name}]"
    except Exception as e:  # never crash the demo on a bad file
        return f"[Could not read {filename}: {e}]"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n\n[...truncated, {len(text) - MAX_CHARS} more characters]"
    return text


def load_table(filename: str, data: bytes):
    import pandas as pd
    if filename.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    return pd.read_excel(io.BytesIO(data))


def dataframe_summary(df, rows: int = 30) -> str:
    """Compact description of a table: schema, stats and sample rows (better than dumping everything)."""
    parts = [
        f"Shape: {df.shape[0]} rows x {df.shape[1]} columns",
        "Columns and types:\n" + "\n".join(f"- {c}: {t}" for c, t in df.dtypes.astype(str).items()),
    ]
    num = df.select_dtypes("number")
    if not num.empty:
        parts.append("Numeric summary:\n" + num.describe().round(2).to_string())
    parts.append(f"First {min(rows, len(df))} rows:\n" + df.head(rows).to_string(index=False))
    return "\n\n".join(parts)


def chunk_text(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    """Split long text for simple retrieval (see core/rag.py)."""
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i:i + size])
        i += size - overlap
    return chunks
