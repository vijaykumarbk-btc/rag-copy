import json
import pickle
import re
from rank_bm25 import BM25Okapi


import os
import sys

DEFAULT_METADATA_FILE = os.getenv("METADATA_FILE", "")
DEFAULT_BM25_INDEX_FILE = os.getenv("BM25_INDEX_FILE", "")


def tokenize(text):
    """Simple lowercase word tokenizer. Good enough for BM25."""
    return re.findall(r"\b\w+\b", text.lower())


def build_bm25_index(metadata_file: str = None, bm25_output_file: str = None):
    metadata_file = metadata_file or DEFAULT_METADATA_FILE
    bm25_output_file = bm25_output_file or DEFAULT_BM25_INDEX_FILE

    if not metadata_file or not bm25_output_file:
        raise ValueError("metadata_file and bm25_output_file must be specified via argument, CLI, or environment variable")

    with open(metadata_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    corpus = []
    for chunk in metadata:
        combined = " ".join(filter(None, [
            chunk.get("parent_section"),
            chunk.get("section"),
            chunk.get("text"),
        ]))
        corpus.append(tokenize(combined))

    bm25 = BM25Okapi(corpus)

    os.makedirs(os.path.dirname(bm25_output_file) if os.path.dirname(bm25_output_file) else ".", exist_ok=True)
    with open(bm25_output_file, "wb") as f:
        pickle.dump(bm25, f)

    print(f"BM25 index built over {len(corpus)} chunks")
    print(f"Saved to: {bm25_output_file}")

    return bm25


if __name__ == "__main__":
    m_path = sys.argv[1] if len(sys.argv) > 1 else None
    b_path = sys.argv[2] if len(sys.argv) > 2 else None
    build_bm25_index(m_path, b_path)