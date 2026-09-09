"""
embedding_with_section.py
-------------------------
Generates contextual dense embeddings for enriched chunks.
- Prepend semantic heading breadcrumb (heading_path) to chunk text.
- Do NOT include artificial IDs (e.g. S9.1.1) in the embedded text.
- Saves aligned (embeddings.npy, metadata.json) maintaining 1:1 positional indexing.
"""

import os
import sys
import json
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST")
MODEL = os.getenv("MODEL")

if not OLLAMA_HOST:
    raise ValueError("OLLAMA_HOST is not set in .env")

if not MODEL:
    raise ValueError("MODEL is not set in .env")

client = OpenAI(
    base_url=OLLAMA_HOST,
    api_key="ollama"
)

print(f"Ollama server: {OLLAMA_HOST}")
print(f"Embedding model: {MODEL}")

# ---------------------------------------------------------------------------
# DEFAULT CONFIGURATION
# ---------------------------------------------------------------------------
DEFAULT_ENRICHED_CHUNKS_FILE = "/home/vijaykumar/Desktop/project2/Lumbar/toc-mapped-chunks/Cigna_Lumbar_Fusion_enriched_chunks.json"
DEFAULT_EMBEDDINGS_FILE = "/home/vijaykumar/Desktop/project2/Lumbar/embeddings/lumbar_fusion_embeddings.npy"
DEFAULT_METADATA_FILE = "/home/vijaykumar/Desktop/project2/Lumbar/embeddings/lumbar_fusion_metadata.json"


def build_embedding_text(chunk: dict) -> str:
    """
    Prepend section hierarchy breadcrumb to chunk text so the embedding captures
    semantic location without leaking synthetic IDs into the vector space.
    """
    heading_path = chunk.get("heading_path")
    if heading_path and isinstance(heading_path, list):
        header = " > ".join(heading_path)
    else:
        parts = []
        parent = chunk.get("parent_section")
        section = chunk.get("section")
        if parent and parent != section:
            parts.append(parent)
        if section:
            parts.append(section)
        header = " > ".join(parts)

    text = chunk.get("text", "").strip()
    if header and text:
        return f"{header}\n\n{text}"
    return text or header or ""


def process_embeddings(
    chunks_path: str = DEFAULT_ENRICHED_CHUNKS_FILE,
    embeddings_out: str = DEFAULT_EMBEDDINGS_FILE,
    metadata_out: str = DEFAULT_METADATA_FILE
):
    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"\nLoaded {len(chunks)} enriched chunks from: {chunks_path}")

    embeddings = []
    metadata = []

    for i, chunk in enumerate(chunks):
        embed_text = build_embedding_text(chunk)
        chunk_copy = dict(chunk)
        chunk_copy["embedded_text"] = embed_text
        chunk_copy["chunk_index"] = i

        try:
            # Handle empty texts gracefully
            if not embed_text.strip():
                embed_text = "Medical Coverage Policy Document"

            response = client.embeddings.create(
                model=MODEL,
                input=embed_text
            )
            embedding = response.data[0].embedding
            embeddings.append(embedding)
            metadata.append(chunk_copy)

            if (i + 1) % 25 == 0 or (i + 1) == len(chunks):
                print(f"Embedded [{i + 1}/{len(chunks)}] chunks...")

        except Exception as e:
            print(f"\nError embedding chunk index {i} (chunk_id {chunk.get('chunk_id')}): {e}")
            raise

    embeddings_arr = np.array(embeddings, dtype=np.float32)
    print(f"\nCompleted! Embedding matrix shape: {embeddings_arr.shape}")

    os.makedirs(os.path.dirname(embeddings_out) if os.path.dirname(embeddings_out) else ".", exist_ok=True)
    np.save(embeddings_out, embeddings_arr)
    print(f"Saved embeddings to: {embeddings_out}")

    os.makedirs(os.path.dirname(metadata_out) if os.path.dirname(metadata_out) else ".", exist_ok=True)
    with open(metadata_out, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Saved metadata to: {metadata_out}")

    assert len(metadata) == len(embeddings_arr), "Invariant violated: metadata count != embedding count!"
    print(f"Invariant check passed: {len(metadata)} rows aligned exactly.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate embeddings with section hierarchy.")
    parser.add_argument("chunks", nargs="?", help="Path to enriched chunks JSON")
    parser.add_argument("embeddings", nargs="?", help="Path to output embeddings .npy")
    parser.add_argument("metadata", nargs="?", help="Path to output metadata JSON")
    parser.add_argument("--chunks", dest="chunks_flag", help="Path to enriched chunks JSON")
    parser.add_argument("--embeddings", dest="emb_flag", help="Path to output embeddings .npy")
    parser.add_argument("--metadata", dest="meta_flag", help="Path to output metadata JSON")
    args = parser.parse_args()

    c_in = args.chunks_flag or args.chunks or DEFAULT_ENRICHED_CHUNKS_FILE
    e_out = args.emb_flag or args.embeddings or DEFAULT_EMBEDDINGS_FILE
    m_out = args.meta_flag or args.metadata or DEFAULT_METADATA_FILE

    if not c_in or not e_out or not m_out:
        print("Usage: python embedding_with_section.py <enriched_chunks.json> <output_embeddings.npy> <output_metadata.json>")
        print("   or: python embedding_with_section.py --chunks <...> --embeddings <...> --metadata <...>")
        sys.exit(1)

    process_embeddings(c_in, e_out, m_out)
