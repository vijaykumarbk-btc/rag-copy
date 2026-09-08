"""
build_bm25.py
-------------
Builds a BM25 index over the enriched metadata chunks.
Ensures tokenization is section-aware (indexing both heading breadcrumbs
and text) for precise keyword matching on medical codes, spinal segments, etc.
"""

import os
import sys
import json
import pickle
import re
from rank_bm25 import BM25Okapi


def build_bm25_index(
    metadata_path: str,
    bm25_output_path: str
):
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    print(f"Loaded {len(metadata)} metadata records for BM25 indexing...")

    corpus = []
    for item in metadata:
        # Index both heading breadcrumb and body text for high term recall
        heading_path = item.get("heading_path", [])
        heading_str = " ".join(heading_path) if isinstance(heading_path, list) else item.get("section", "")
        full_text = f"{heading_str} {item.get('text', '')}"
        corpus.append(tokenize(full_text))

    bm25 = BM25Okapi(corpus)

    os.makedirs(os.path.dirname(bm25_output_path) if os.path.dirname(bm25_output_path) else ".", exist_ok=True)
    with open(bm25_output_path, "wb") as f:
        pickle.dump({"bm25": bm25, "corpus": corpus}, f)

    print(f"BM25 index successfully saved to: {bm25_output_path}")
    return bm25


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build BM25 index from metadata chunks.")
    parser.add_argument("metadata", nargs="?", help="Path to *_metadata.json")
    parser.add_argument("output", nargs="?", help="Path to output *_bm25.pkl")
    parser.add_argument("--metadata", dest="meta_flag", help="Path to *_metadata.json")
    parser.add_argument("--output", dest="out_flag", help="Path to output *_bm25.pkl")
    args = parser.parse_args()

    m_in = args.meta_flag or args.metadata
    b_out = args.out_flag or args.output

    if not m_in or not b_out:
        print("Usage: python build_bm25.py <metadata_file> <output_bm25_file>")
        print("   or: python build_bm25.py --metadata <metadata_file> --output <output_bm25_file>")
        sys.exit(1)

    build_bm25_index(m_in, b_out)

