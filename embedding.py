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

CHUNKS_FILE = "data/chunks/Cigna_ACDF_chunks.json"

with open(
    CHUNKS_FILE,
    "r",
    encoding="utf-8"
) as f:
    chunks = json.load(f)

print(f"Loaded {len(chunks)} chunks")


embeddings = []

for i, chunk in enumerate(chunks):

    text = chunk["text"]

    try:

        response = client.embeddings.create(
            model=MODEL,
            input=text
        )

        embedding = response.data[0].embedding

        embeddings.append(embedding)

        print(
            f"Embedded {i + 1}/{len(chunks)}"
        )

    except Exception as e:

        print(
            f"\nError embedding chunk {i + 1}: {e}"
        )

        raise



embeddings = np.array(
    embeddings,
    dtype=np.float32
)

print(
    "\nEmbedding shape:",
    embeddings.shape
)


EMBEDDINGS_FILE = (
    "data/chunks/Cigna_ACDF_embeddings.npy"
)

np.save(
    EMBEDDINGS_FILE,
    embeddings
)

print(
    f"Embeddings saved to: {EMBEDDINGS_FILE}"
)


METADATA_FILE = (
    "data/chunks/Cigna_ACDF_metadata.json"
)

metadata = []

for i, chunk in enumerate(chunks):

    metadata.append({
        "chunk_id": i,
        **chunk
    })


with open(
    METADATA_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        metadata,
        f,
        indent=2,
        ensure_ascii=False
    )

print(
    f"Metadata saved to: {METADATA_FILE}"
)