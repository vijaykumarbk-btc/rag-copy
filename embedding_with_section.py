import os
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

print("Ollama server:", OLLAMA_HOST)
print("Embedding model:", MODEL)

CHUNKS_FILE = "data/chunks/new/Lumbar_CLOUDCONVERT_chunks.json"

with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
    chunks = json.load(f)

print(f"Loaded {len(chunks)} chunks")


def build_embedding_text(chunk):
    """
    Prepend section hierarchy context to the chunk text so the
    embedding captures *what topic/section* this chunk belongs to,
    not just its raw sentence content.
    """
    parts = []

    parent = chunk.get("parent_section")
    section = chunk.get("section")

    if parent and parent != section:
        parts.append(parent)
    if section:
        parts.append(section)

    header = " > ".join(parts)

    if header:
        return f"{header}\n\n{chunk['text']}"
    return chunk["text"]


embeddings = []

for i, chunk in enumerate(chunks):

    embed_text = build_embedding_text(chunk)

    # store exactly what was embedded, for debugging/traceability
    chunk["embedded_text"] = embed_text

    try:
        response = client.embeddings.create(
            model=MODEL,
            input=embed_text
        )

        embedding = response.data[0].embedding
        embeddings.append(embedding)

        print(f"Embedded {i + 1}/{len(chunks)}")

    except Exception as e:
        print(f"\nError embedding chunk {i + 1}: {e}")
        raise


embeddings = np.array(embeddings, dtype=np.float32)

print("\nEmbedding shape:", embeddings.shape)


EMBEDDINGS_FILE = "data/embeddings/new_embeddings_CLOUDCONVERT/Lumbar_CLOUDCONVERT_embeddings.npy"

np.save(EMBEDDINGS_FILE, embeddings)

print(f"Embeddings saved to: {EMBEDDINGS_FILE}")


METADATA_FILE = "data/embeddings/new_embeddings_CLOUDCONVERT/Lumbar_CLOUDCONVERT_metadata.json"

metadata = []

for i, chunk in enumerate(chunks):
    metadata.append({
        "chunk_id": i,
        **chunk   # now also includes "embedded_text"
    })


with open(METADATA_FILE, "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2, ensure_ascii=False)

print(f"Metadata saved to: {METADATA_FILE}")
